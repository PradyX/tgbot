import html
import random
import re
import string
import time

from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          MessageHandler, filters)
from telegram.helpers import mention_html

from tg_bot import dispatcher, LOGGER, OWNER_ID, SUDO_USERS, SUPPORT_USERS, WHITELIST_USERS
from tg_bot.modules.helper_funcs.chat_status import is_user_admin, user_admin
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql import captcha_sql as sql

# Handler groups: the gate runs before normal handlers (so unruly messages never reach
# filters/notes), the member handlers run after the welcome module's.
GATE_GROUP = -50
MEMBER_GROUP = 5

MAX_ATTEMPTS = 3
NOTICE_DELETE_SECONDS = 300
MIN_TIMEOUT = 30
MAX_TIMEOUT = 600

BUTTON_LABELS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel",
                 "Lima", "Mike", "November", "Oscar", "Quebec", "Romeo", "Sierra", "Tango"]

TRUSTED = set(SUDO_USERS) | set(SUPPORT_USERS) | set(WHITELIST_USERS) | {OWNER_ID}

# everything off - used to hold newcomers until they pass the captcha
NO_PERMS = ChatPermissions(can_send_messages=False, can_send_audios=False,
                           can_send_documents=False, can_send_photos=False,
                           can_send_videos=False, can_send_video_notes=False,
                           can_send_voice_notes=False, can_send_polls=False,
                           can_send_other_messages=False, can_add_web_page_previews=False,
                           can_change_info=False, can_invite_users=False,
                           can_pin_messages=False, can_manage_topics=False)

# fallback used when the chat has no explicit default member permissions
DEFAULT_PERMS = ChatPermissions(can_send_messages=True, can_send_audios=True,
                                can_send_documents=True, can_send_photos=True,
                                can_send_videos=True, can_send_video_notes=True,
                                can_send_voice_notes=True, can_send_polls=True,
                                can_send_other_messages=True, can_add_web_page_previews=True,
                                can_change_info=False, can_invite_users=True,
                                can_pin_messages=False, can_manage_topics=False)


def _job_name(chat_id, user_id):
    return "captcha_{}_{}".format(chat_id, user_id)


def _cancel_job(context, chat_id, user_id):
    for job in context.job_queue.get_jobs_by_name(_job_name(chat_id, user_id)):
        job.schedule_removal()


def _button_keyboard(chat_id, user_id, labels):
    keyboard = []
    row = []
    for idx, label in enumerate(labels):
        row.append(InlineKeyboardButton(label,
                                        callback_data="captcha_{}_{}_{}".format(chat_id, user_id, idx)))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


def _new_challenge(chat_id, user_name, user_id, captcha_type, timeout):
    """Build (text, answer, keyboard) for a fresh challenge."""
    mention = mention_html(user_id, user_name)
    keyboard = None

    if captcha_type == "math":
        a, b = random.randint(2, 12), random.randint(2, 12)
        answer = str(a * b)
        text = ("⚠️ {}, welcome! To prove you're human, solve this quick captcha:\n\n"
                "<b>What is {} × {}?</b>\n\n"
                "Type the answer within {} seconds, or you'll be kicked."
                ).format(mention, a, b, timeout)
    elif captcha_type == "word":
        answer = "".join(random.choices(string.ascii_lowercase, k=5))
        text = ("⚠️ {}, welcome! To prove you're human, type this word:\n\n"
                "<code>{}</code>\n\n"
                "Send it as a message within {} seconds, or you'll be kicked."
                ).format(mention, answer, timeout)
    else:  # button
        labels = random.sample(BUTTON_LABELS, 4)
        correct = random.randrange(4)
        answer = str(correct)
        text = ("⚠️ {}, welcome! To prove you're human, press the button labelled\n"
                "<b>{}</b>\n\n"
                "You have {} seconds, or you'll be kicked."
                ).format(mention, html.escape(labels[correct]), timeout)
        keyboard = _button_keyboard(chat_id, user_id, labels)

    return text, answer, keyboard


async def _clear_challenge(context, pending, delete_message=True):
    """Remove a pending challenge: cancel its timeout job and delete the challenge message."""
    _cancel_job(context, pending.chat_id, pending.user_id)
    sql.rm_pending(pending.chat_id, pending.user_id)
    if delete_message and pending.message_id:
        try:
            await context.bot.delete_message(pending.chat_id, pending.message_id)
        except (BadRequest, Forbidden):
            pass


async def _restore_perms(context, chat_id, user_id):
    """Lift the captcha mute, restoring the chat's default member permissions."""
    try:
        chat = await context.bot.get_chat(chat_id)
        perms = chat.permissions
        if not perms or not perms.can_send_messages:
            perms = DEFAULT_PERMS
        await chat.restrict_member(user_id, permissions=perms)
    except (BadRequest, Forbidden):
        pass


async def _pass_challenge(context, pending):
    await _clear_challenge(context, pending)
    await _restore_perms(context, pending.chat_id, pending.user_id)


async def _fail_challenge(context, pending):
    """Kick (ban + unban) a user who failed the captcha, and leave a self-deleting notice."""
    await _clear_challenge(context, pending)
    kicked = True
    try:
        chat = await context.bot.get_chat(pending.chat_id)
        await chat.ban_member(pending.user_id)
        await chat.unban_member(pending.user_id)
    except (BadRequest, Forbidden) as excp:
        kicked = False
        LOGGER.warning("Could not kick captcha-failing user %s in %s: %s",
                       pending.user_id, pending.chat_id, excp)

    if not kicked:
        return

    mention = mention_html(pending.user_id, pending.user_name or "user")
    try:
        notice = await context.bot.send_message(
            pending.chat_id,
            "❌ {} failed the captcha and has been kicked.".format(mention),
            parse_mode=ParseMode.HTML)
        context.job_queue.run_once(delete_notice, NOTICE_DELETE_SECONDS,
                                   data=(pending.chat_id, notice.message_id),
                                   name="captcha_notice_{}_{}".format(pending.chat_id,
                                                                      notice.message_id))
    except (BadRequest, Forbidden):
        pass


async def new_member(update, context):
    chat = update.effective_chat
    msg = update.effective_message

    enabled, captcha_type, timeout = sql.get_settings(chat.id)
    if not enabled:
        return

    for new_mem in msg.new_chat_members:
        # never challenge bots, the trusted user lists, or admins
        if new_mem.is_bot or new_mem.id in TRUSTED:
            continue
        if await is_user_admin(chat, new_mem.id):
            continue

        text, answer, keyboard = _new_challenge(chat.id, new_mem.first_name or "newcomer",
                                                new_mem.id, captcha_type, timeout)
        try:
            sent = await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except BadRequest:
            sent = await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML,
                                                  reply_markup=keyboard)

        sql.add_pending(chat.id, new_mem.id, new_mem.first_name, sent.message_id, answer,
                        captcha_type, timeout)

        # button captchas mute until solved; text captchas need the user unmuted to answer,
        # so those rely on the message gate instead.
        if captcha_type == "button":
            try:
                await chat.restrict_member(new_mem.id, permissions=NO_PERMS)
            except (BadRequest, Forbidden):
                pass

        context.job_queue.run_once(captcha_timeout, timeout,
                                   data=(chat.id, new_mem.id),
                                   name=_job_name(chat.id, new_mem.id))


async def left_member(update, context):
    chat = update.effective_chat
    left = update.effective_message.left_chat_member
    if not left:
        return

    pending = sql.get_pending(chat.id, left.id)
    if pending:
        await _clear_challenge(context, pending)


async def captcha_message(update, context):
    """Gate: messages from users with a pending captcha are deleted unless they're the answer."""
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message

    if not user or not chat:
        return

    pending = sql.get_pending(chat.id, user.id)
    if not pending:
        return

    # if they got promoted mid-challenge, let them off
    if await is_user_admin(chat, user.id):
        await _clear_challenge(context, pending)
        await _restore_perms(context, chat.id, user.id)
        return

    answer_text = (msg.text or "").strip()
    solved = False
    if answer_text:
        if pending.captcha_type == "math":
            solved = answer_text == pending.answer
        elif pending.captcha_type == "word":
            solved = answer_text.lower() == pending.answer.lower()

    if solved:
        try:
            await msg.delete()
        except (BadRequest, Forbidden):
            pass
        await _pass_challenge(context, pending)
    else:
        try:
            await msg.delete()
        except (BadRequest, Forbidden):
            # can't delete? then hold them back the hard way
            try:
                await chat.restrict_member(user.id, permissions=NO_PERMS)
            except (BadRequest, Forbidden):
                pass
        attempts = sql.bump_attempts(pending.id)
        if attempts >= MAX_ATTEMPTS:
            await _fail_challenge(context, pending)

    # never let a pending user's messages through to filters/notes/etc
    raise ApplicationHandlerStop


async def captcha_button(update, context):
    query = update.callback_query
    match = re.fullmatch(r"captcha_(-?\d+)_(\d+)_(\d+)", query.data or "")
    if not match:
        return

    chat_id, user_id, idx = int(match.group(1)), int(match.group(2)), int(match.group(3))
    pending = sql.get_pending(chat_id, user_id)
    if not pending:
        await query.answer("This captcha has expired.", show_alert=True)
        try:
            await query.message.delete()
        except (BadRequest, Forbidden):
            pass
        return

    if query.from_user.id != user_id:
        await query.answer("This isn't your captcha - hands off!", show_alert=True)
        return

    if str(idx) == pending.answer:
        await query.answer("Verified - welcome!")
        await _pass_challenge(context, pending)
        return

    attempts = sql.bump_attempts(pending.id)
    if attempts >= MAX_ATTEMPTS:
        await query.answer("Wrong button - you're out.")
        await _fail_challenge(context, pending)
        return

    # wrong button: reshuffle so it can't be brute forced
    text, answer, keyboard = _new_challenge(chat_id, pending.user_name or "newcomer", user_id,
                                            "button", sql.get_settings(chat_id)[2])
    sql.set_answer(pending.id, answer)
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest:
        pass
    await query.answer("Wrong button - try again!")


async def captcha_timeout(context):
    chat_id, user_id = context.job.data
    pending = sql.get_pending(chat_id, user_id)
    if pending:
        await _fail_challenge(context, pending)


async def delete_notice(context):
    chat_id, message_id = context.job.data
    try:
        await context.bot.delete_message(chat_id, message_id)
    except (BadRequest, Forbidden):
        pass


@user_admin
@loggable
async def captcha(update, context) -> str:
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    enabled, captcha_type, timeout = sql.get_settings(chat.id)

    if not args:
        await msg.reply_text(
            "Join captcha is currently *{}*.\n"
            "Captcha type: `{}`\n"
            "Timeout: `{}s`\n\n"
            "Use `/captcha on|off`, `/captcha button|math|word`, or `/captchatimeout <seconds>` to change it."
            .format("on" if enabled else "off", captcha_type, timeout),
            parse_mode=ParseMode.MARKDOWN)
        return ""

    arg = args[0].lower()
    if arg in ("on", "yes"):
        sql.set_enabled(chat.id, True)
        await msg.reply_text("Join captcha enabled! Newcomers must solve a captcha before they can post.")
        return "<b>{}:</b>" \
               "\n#SET_CAPTCHA" \
               "\n<b>Admin:</b> {}" \
               "\nEnabled the join captcha.".format(html.escape(chat.title),
                                                    mention_html(user.id, user.first_name))

    elif arg in ("off", "no"):
        sql.set_enabled(chat.id, False)
        await msg.reply_text("Join captcha disabled - everyone can post freely again.")
        return "<b>{}:</b>" \
               "\n#SET_CAPTCHA" \
               "\n<b>Admin:</b> {}" \
               "\nDisabled the join captcha.".format(html.escape(chat.title),
                                                     mention_html(user.id, user.first_name))

    elif arg in ("button", "math", "word"):
        sql.set_captcha_type(chat.id, arg)
        await msg.reply_text("Captcha type set to `{}`.".format(arg), parse_mode=ParseMode.MARKDOWN)
        return "<b>{}:</b>" \
               "\n#SET_CAPTCHA" \
               "\n<b>Admin:</b> {}" \
               "\nSet the captcha type to <code>{}</code>.".format(html.escape(chat.title),
                                                                   mention_html(user.id, user.first_name),
                                                                   arg)

    await msg.reply_text("I understand 'on/off', or a captcha type: 'button', 'math', 'word'.")
    return ""


@user_admin
@loggable
async def captcha_timeout_cmd(update, context) -> str:
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not args or not args[0].isdigit():
        await msg.reply_text("Usage: `/captchatimeout <seconds>` ({}-{}).".format(MIN_TIMEOUT, MAX_TIMEOUT),
                             parse_mode=ParseMode.MARKDOWN)
        return ""

    seconds = int(args[0])
    if not MIN_TIMEOUT <= seconds <= MAX_TIMEOUT:
        await msg.reply_text("The timeout has to be between {} and {} seconds.".format(MIN_TIMEOUT, MAX_TIMEOUT))
        return ""

    sql.set_timeout(chat.id, seconds)
    await msg.reply_text("Newcomers now have {} seconds to solve the captcha.".format(seconds))
    return "<b>{}:</b>" \
           "\n#SET_CAPTCHA" \
           "\n<b>Admin:</b> {}" \
           "\nSet the captcha timeout to <code>{}</code>s.".format(html.escape(chat.title),
                                                                   mention_html(user.id, user.first_name),
                                                                   seconds)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    enabled, captcha_type, timeout = sql.get_settings(chat_id)
    return "Join captcha is `{}`, type `{}`, timeout `{}s`.".format(
        "on" if enabled else "off", captcha_type, timeout)


def _reschedule_pending():
    """Re-arm timeout jobs for challenges that survived a restart."""
    now = time.time()
    for pending in sql.get_all_pending():
        remaining = max(1, pending.expiry - now)
        dispatcher.job_queue.run_once(captcha_timeout, remaining,
                                      data=(pending.chat_id, pending.user_id),
                                      name=_job_name(pending.chat_id, pending.user_id))


__help__ = """
 - /captcha: view the current captcha settings.

*Admin only:*
 - /captcha on|off: enable or disable the captcha newcomers must solve before they can post.
 - /captcha <button|math|word>: pick the captcha style.
 - /captchatimeout <seconds>: how long a newcomer has to solve the captcha ({min}-{max}s) before being \
kicked. Wrong answers are deleted; {max_attempts} wrong attempts also lead to a kick.

Newcomers can't post until they pass; button captchas also mute them until they click. Admins, bots, and \
the sudo/support/whitelist users are never challenged. Pairs nicely with antiflood and raid protection.
""".format(min=MIN_TIMEOUT, max=MAX_TIMEOUT, max_attempts=MAX_ATTEMPTS)

__mod_name__ = "Captcha"

NEW_MEM_HANDLER = MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.ChatType.GROUPS,
                                 new_member)
LEFT_MEM_HANDLER = MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER & filters.ChatType.GROUPS,
                                  left_member)
CAPTCHA_MSG_HANDLER = MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL & filters.ChatType.GROUPS,
                                     captcha_message)
CAPTCHA_BUTTON_HANDLER = CallbackQueryHandler(captcha_button, pattern=r"^captcha_")
CAPTCHA_HANDLER = CommandHandler("captcha", captcha, filters=filters.ChatType.GROUPS)
CAPTCHA_TIMEOUT_HANDLER = CommandHandler("captchatimeout", captcha_timeout_cmd,
                                         filters=filters.ChatType.GROUPS)

dispatcher.add_handler(NEW_MEM_HANDLER, MEMBER_GROUP)
dispatcher.add_handler(LEFT_MEM_HANDLER, MEMBER_GROUP)
dispatcher.add_handler(CAPTCHA_MSG_HANDLER, GATE_GROUP)
dispatcher.add_handler(CAPTCHA_BUTTON_HANDLER)
dispatcher.add_handler(CAPTCHA_HANDLER)
dispatcher.add_handler(CAPTCHA_TIMEOUT_HANDLER)

_reschedule_pending()
