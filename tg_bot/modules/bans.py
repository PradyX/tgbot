import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram.error import BadRequest
from telegram.ext import CommandHandler, filters
from telegram.helpers import mention_html

from tg_bot import dispatcher, BAN_STICKER, LOGGER
from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot.modules.helper_funcs.chat_status import bot_admin, user_admin, is_user_ban_protected, can_restrict, \
    is_user_admin, is_user_in_chat
from tg_bot.modules.helper_funcs.extraction import extract_user_and_text
from tg_bot.modules.helper_funcs.string_handling import extract_time
from tg_bot.modules.log_channel import loggable


@bot_admin
@can_restrict
@user_admin
@loggable
async def ban(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    message = update.effective_message  # type: Optional[Message]

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.reply_text("You don't seem to be referring to a user.")
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest as excp:
        if excp.message == "User not found":
            await message.reply_text("I can't seem to find this user")
            return ""
        else:
            raise

    if await is_user_ban_protected(chat, user_id, member):
        await message.reply_text("Why?")
        return ""

    if user_id == bot.id:
        await message.reply_text("Oh yeah, ban myself, noob!")
        return ""

    log = "<b>{}:</b>" \
          "\n#BANNED" \
          "\n<b>Admin:</b> {}" \
          "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                       mention_html(user.id, user.first_name),
                                                       mention_html(member.user.id, member.user.first_name),
                                                       member.user.id)
    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        await chat.ban_member(user_id)
        await bot.send_sticker(chat.id, BAN_STICKER)  # banhammer marie sticker
        await message.reply_text("Banned!")
        return log

    except BadRequest as excp:
        if excp.message == "Reply message not found":
            # Do not reply
            await message.reply_text('Banned!', quote=False)
            return log
        else:
            LOGGER.warning(update)
            LOGGER.exception("ERROR banning user %s in chat %s (%s) due to %s", user_id, chat.title, chat.id,
                             excp.message)
            await message.reply_text("Well damn, I can't ban that user.")

    return ""


@bot_admin
@can_restrict
@user_admin
@loggable
async def temp_ban(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    message = update.effective_message  # type: Optional[Message]

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.reply_text("You don't seem to be referring to a user.")
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest as excp:
        if excp.message == "User not found":
            await message.reply_text("I can't seem to find this user")
            return ""
        else:
            raise

    if await is_user_ban_protected(chat, user_id, member):
        await message.reply_text("Yeah sure, ban your GOD!! NOOOB!.")
        return ""

    if user_id == bot.id:
        await message.reply_text("Oh yeah, ban myself, noob!")
        return ""

    if not reason:
        await message.reply_text("You haven't specified a time to ban this user for!")
        return ""

    split_reason = reason.split(None, 1)

    time_val = split_reason[0].lower()
    if len(split_reason) > 1:
        reason = split_reason[1]
    else:
        reason = ""

    bantime = await extract_time(message, time_val)

    if not bantime:
        return ""

    log = "<b>{}:</b>" \
          "\n#TEMP BANNED" \
          "\n<b>Admin:</b> {}" \
          "\n<b>User:</b> {} (<code>{}</code>)" \
          "\n<b>Time:</b> {}".format(html.escape(chat.title),
                                     mention_html(user.id, user.first_name),
                                     mention_html(member.user.id, member.user.first_name),
                                     member.user.id,
                                     time_val)
    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        await chat.ban_member(user_id, until_date=bantime)
        await bot.send_sticker(chat.id, BAN_STICKER)  # banhammer marie sticker
        await message.reply_text("Justice has been served you little shi.... This user will be banned for {}.".format(time_val))
        return log

    except BadRequest as excp:
        if excp.message == "Reply message not found":
            # Do not reply
            await message.reply_text("Justice has been served you little shi.... This user will be banned for {}.".format(time_val), quote=False)
            return log
        else:
            LOGGER.warning(update)
            LOGGER.exception("ERROR banning user %s in chat %s (%s) due to %s", user_id, chat.title, chat.id,
                             excp.message)
            await message.reply_text("Well damn, I can't ban that user.")

    return ""


@bot_admin
@can_restrict
@user_admin
@loggable
async def kick(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    message = update.effective_message  # type: Optional[Message]

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest as excp:
        if excp.message == "User not found":
            await message.reply_text("I can't seem to find this user")
            return ""
        else:
            raise

    if await is_user_ban_protected(chat, user_id):
        await message.reply_text("Why?")
        return ""

    if user_id == bot.id:
        await message.reply_text("Oh yeah, kick myself, noob!")
        return ""

    res = await chat.unban_member(user_id)  # unban on current user = kick
    if res:
        await bot.send_sticker(chat.id, BAN_STICKER)  # banhammer marie sticker
        await message.reply_text("Kicked!")
        log = "<b>{}:</b>" \
              "\n#KICKED" \
              "\n<b>Admin:</b> {}" \
              "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                           mention_html(user.id, user.first_name),
                                                           mention_html(member.user.id, member.user.first_name),
                                                           member.user.id)
        if reason:
            log += "\n<b>Reason:</b> {}".format(reason)

        return log

    else:
        await message.reply_text("Well damn, I can't kick that user.")

    return ""


@bot_admin
@can_restrict
async def kickme(update, context):
    bot = context.bot
    user_id = update.effective_message.from_user.id
    if await is_user_admin(update.effective_chat, user_id):
        await update.effective_message.reply_text("I wish I could... but you're an admin.")
        return

    res = await update.effective_chat.unban_member(user_id)  # unban on current user = kick
    if res:
        await update.effective_message.reply_text("No problem.")
    else:
        await update.effective_message.reply_text("Huh? I can't :/")


@bot_admin
@can_restrict
@user_admin
@loggable
async def unban(update, context) -> str:
    bot = context.bot
    args = context.args
    message = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]
    chat = update.effective_chat  # type: Optional[Chat]

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        return ""

    try:
        member = await chat.get_member(user_id)
    except BadRequest as excp:
        if excp.message == "User not found":
            await message.reply_text("I can't seem to find this user")
            return ""
        else:
            raise

    if user_id == bot.id:
        await message.reply_text("How would I unban myself if I wasn't here...?")
        return ""

    if await is_user_in_chat(chat, user_id):
        await message.reply_text("Why are you trying to unban someone that's already in the chat?")
        return ""

    await chat.unban_member(user_id)
    await message.reply_text("Yep, this user can join!")

    log = "<b>{}:</b>" \
          "\n#UNBANNED" \
          "\n<b>Admin:</b> {}" \
          "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                       mention_html(user.id, user.first_name),
                                                       mention_html(member.user.id, member.user.first_name),
                                                       member.user.id)
    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    return log


__help__ = """
 - /kickme: kicks the user who issued the command

*Admin only:*
 - /ban <userhandle>: bans a user. (via handle, or reply)
 - /tban <userhandle> x(m/h/d): bans a user for x time. (via handle, or reply). m = minutes, h = hours, d = days.
 - /unban <userhandle>: unbans a user. (via handle, or reply)
 - /kick <userhandle>: kicks a user, (via handle, or reply)
"""

__mod_name__ = "Bans"

BAN_HANDLER = CommandHandler("ban", ban, filters=filters.ChatType.GROUPS)
TEMPBAN_HANDLER = CommandHandler(["tban", "tempban"], temp_ban, filters=filters.ChatType.GROUPS)
KICK_HANDLER = CommandHandler("kick", kick, filters=filters.ChatType.GROUPS)
UNBAN_HANDLER = CommandHandler("unban", unban, filters=filters.ChatType.GROUPS)
KICKME_HANDLER = DisableAbleCommandHandler("kickme", kickme, filters=filters.ChatType.GROUPS)

dispatcher.add_handler(BAN_HANDLER)
dispatcher.add_handler(TEMPBAN_HANDLER)
dispatcher.add_handler(KICK_HANDLER)
dispatcher.add_handler(UNBAN_HANDLER)
dispatcher.add_handler(KICKME_HANDLER)
