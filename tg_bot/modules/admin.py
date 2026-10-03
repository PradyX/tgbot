import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CommandHandler, filters
from telegram.helpers import escape_markdown, mention_html

from tg_bot import dispatcher
from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot.modules.helper_funcs.chat_status import bot_admin, can_promote, user_admin, can_pin
from tg_bot.modules.helper_funcs.extraction import extract_user, extract_user_and_text
from tg_bot.modules.log_channel import loggable


@bot_admin
@can_promote
@user_admin
@loggable
async def promote(update, context) -> str:
    bot = context.bot
    args = context.args
    chat_id = update.effective_chat.id
    message = update.effective_message  # type: Optional[Message]
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]

    user_id, title = await extract_user_and_text(message, args)
    if not user_id:
        await message.reply_text("You don't seem to be referring to a user.")
        return ""

    user_member = await chat.get_member(user_id)
    if user_member.status == 'administrator' or user_member.status == 'creator':
        await message.reply_text("How am I meant to promote someone that's already an admin?")
        return ""

    if user_id == bot.id:
        await message.reply_text("I can't promote myself! Get an admin to do it for me.")
        return ""

    # set same perms as bot - bot can't assign higher perms than itself!
    bot_member = await chat.get_member(bot.id)

    await bot.promote_chat_member(chat_id, user_id,
                          can_change_info=bot_member.can_change_info,
                          can_post_messages=bot_member.can_post_messages,
                          can_edit_messages=bot_member.can_edit_messages,
                          can_delete_messages=bot_member.can_delete_messages,
                          # can_invite_users=bot_member.can_invite_users,
                          can_restrict_members=bot_member.can_restrict_members,
                          can_pin_messages=bot_member.can_pin_messages,
                          can_promote_members=bot_member.can_promote_members)

    if title:
        try:
            await bot.set_chat_administrator_custom_title(chat_id, user_id, title[:16])
            await message.reply_text("Successfully promoted {} with the title `{}`!".format(
                mention_html(user_member.user.id, user_member.user.first_name), html.escape(title[:16])),
                parse_mode=ParseMode.HTML)
        except BadRequest as excp:
            await message.reply_text("Promoted, but couldn't set the custom title: {}".format(excp.message))
    else:
        await message.reply_text("Successfully promoted!")
    return "<b>{}:</b>" \
           "\n#PROMOTED" \
           "\n<b>Admin:</b> {}" \
           "\n<b>User:</b> {}".format(html.escape(chat.title),
                                      mention_html(user.id, user.first_name),
                                      mention_html(user_member.user.id, user_member.user.first_name))


@bot_admin
@can_promote
@user_admin
@loggable
async def demote(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    message = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text("You don't seem to be referring to a user.")
        return ""

    user_member = await chat.get_member(user_id)
    if user_member.status == 'creator':
        await message.reply_text("This person CREATED the chat, how would I demote them?")
        return ""

    if not user_member.status == 'administrator':
        await message.reply_text("Can't demote what wasn't promoted!")
        return ""

    if user_id == bot.id:
        await message.reply_text("I can't demote myself! Get an admin to do it for me.")
        return ""

    try:
        await bot.promote_chat_member(int(chat.id), int(user_id),
                              can_change_info=False,
                              can_post_messages=False,
                              can_edit_messages=False,
                              can_delete_messages=False,
                              can_invite_users=False,
                              can_restrict_members=False,
                              can_pin_messages=False,
                              can_promote_members=False)
        await message.reply_text("Successfully demoted!")
        return "<b>{}:</b>" \
               "\n#DEMOTED" \
               "\n<b>Admin:</b> {}" \
               "\n<b>User:</b> {}".format(html.escape(chat.title),
                                          mention_html(user.id, user.first_name),
                                          mention_html(user_member.user.id, user_member.user.first_name))

    except BadRequest:
        await message.reply_text("Could not demote. I might not be admin, or the admin status was appointed by another "
                           "user, so I can't act upon them!")
        return ""


@bot_admin
@can_pin
@user_admin
@loggable
async def pin(update, context) -> str:
    bot = context.bot
    args = context.args
    user = update.effective_user  # type: Optional[User]
    chat = update.effective_chat  # type: Optional[Chat]

    is_group = chat.type != "private" and chat.type != "channel"

    prev_message = update.effective_message.reply_to_message

    is_silent = True
    if len(args) >= 1:
        is_silent = not (args[0].lower() == 'notify' or args[0].lower() == 'loud' or args[0].lower() == 'violent')

    if prev_message and is_group:
        try:
            await bot.pin_chat_message(chat.id, prev_message.message_id, disable_notification=is_silent)
        except BadRequest as excp:
            if excp.message == "Chat_not_modified":
                pass
            else:
                raise
        return "<b>{}:</b>" \
               "\n#PINNED" \
               "\n<b>Admin:</b> {}".format(html.escape(chat.title), mention_html(user.id, user.first_name))

    return ""


@bot_admin
@can_pin
@user_admin
@loggable
async def unpin(update, context) -> str:
    bot = context.bot
    chat = update.effective_chat
    user = update.effective_user  # type: Optional[User]

    try:
        await bot.unpin_chat_message(chat.id)
    except BadRequest as excp:
        if excp.message == "Chat_not_modified":
            pass
        else:
            raise

    return "<b>{}:</b>" \
           "\n#UNPINNED" \
           "\n<b>Admin:</b> {}".format(html.escape(chat.title),
                                       mention_html(user.id, user.first_name))


@bot_admin
@user_admin
@loggable
async def set_gtitle(update, context):
    bot = context.bot
    chat = update.effective_chat
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    if not args:
        await msg.reply_text("Give me the new group title! Usage: `/setgtitle <title>`",
                             parse_mode=ParseMode.MARKDOWN)
        return ""

    title = msg.text.split(None, 1)[1]
    await bot.set_chat_title(chat.id, title)
    await msg.reply_text("Group title updated!")
    return "<b>{}:</b>" \
           "\n#SETGTITLE" \
           "\n<b>Admin:</b> {}" \
           "\nNew title: <code>{}</code>".format(html.escape(chat.title),
                                                mention_html(update.effective_user.id,
                                                             update.effective_user.first_name),
                                                html.escape(title))


@bot_admin
@user_admin
@loggable
async def set_gdesc(update, context):
    bot = context.bot
    chat = update.effective_chat
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    if not args:
        await msg.reply_text("Give me the new group description! Usage: `/setgdesc <description>`",
                             parse_mode=ParseMode.MARKDOWN)
        return ""

    desc = msg.text.split(None, 1)[1]
    await bot.set_chat_description(chat.id, desc)
    await msg.reply_text("Group description updated!")
    return "<b>{}:</b>" \
           "\n#SETGDESC" \
           "\n<b>Admin:</b> {}".format(html.escape(chat.title),
                                       mention_html(update.effective_user.id,
                                                    update.effective_user.first_name))


@bot_admin
@user_admin
async def invite(update, context):
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]
    if chat.username:
        await update.effective_message.reply_text(chat.username)
    elif chat.type == chat.SUPERGROUP or chat.type == chat.CHANNEL:
        bot_member = await chat.get_member(bot.id)
        if bot_member.can_invite_users:
            invitelink = await bot.export_chat_invite_link(chat.id)
            await update.effective_message.reply_text(invitelink)
        else:
            await update.effective_message.reply_text("I don't have access to the invite link, try changing my permissions!")
    else:
        await update.effective_message.reply_text("I can only give you invite links for supergroups and channels, sorry!")


async def adminlist(update, context):
    bot = context.bot
    administrators = await update.effective_chat.get_administrators()
    text = "Admins in *{}*:".format(update.effective_chat.title or "this chat")
    for admin in administrators:
        user = admin.user
        name = "[{}](tg://user?id={})".format(user.first_name + (user.last_name or ""), user.id)
        if user.username:
            name = escape_markdown("@" + user.username)
        text += "\n - {}".format(name)

    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def __chat_settings__(chat_id, user_id):
    return "You are *admin*: `{}`".format(
        (await dispatcher.bot.get_chat_member(chat_id, user_id)).status in ("administrator", "creator"))


__help__ = """
 - /adminlist: list of admins in the chat

*Admin only:*
 - /pin: silently pins the message replied to - add 'loud' or 'notify' to give notifs to users.
 - /unpin: unpins the currently pinned message
 - /invitelink: gets invitelink
 - /promote <userhandle> [title]: promotes the user replied to (or specified), with an optional custom admin title
 - /demote: demotes the user replied to
 - /setgtitle <title>: sets the group title
 - /setgdesc <description>: sets the group description
"""

__mod_name__ = "Admin"

PIN_HANDLER = CommandHandler("pin", pin, filters=filters.ChatType.GROUPS)
UNPIN_HANDLER = CommandHandler("unpin", unpin, filters=filters.ChatType.GROUPS)

INVITE_HANDLER = CommandHandler("invitelink", invite, filters=filters.ChatType.GROUPS)

PROMOTE_HANDLER = CommandHandler("promote", promote, filters=filters.ChatType.GROUPS)
DEMOTE_HANDLER = CommandHandler("demote", demote, filters=filters.ChatType.GROUPS)
SETGTITLE_HANDLER = CommandHandler("setgtitle", set_gtitle, filters=filters.ChatType.GROUPS)
SETGDESC_HANDLER = CommandHandler("setgdesc", set_gdesc, filters=filters.ChatType.GROUPS)

ADMINLIST_HANDLER = DisableAbleCommandHandler("adminlist", adminlist, filters=filters.ChatType.GROUPS)

dispatcher.add_handler(PIN_HANDLER)
dispatcher.add_handler(UNPIN_HANDLER)
dispatcher.add_handler(INVITE_HANDLER)
dispatcher.add_handler(PROMOTE_HANDLER)
dispatcher.add_handler(DEMOTE_HANDLER)
dispatcher.add_handler(SETGTITLE_HANDLER)
dispatcher.add_handler(SETGDESC_HANDLER)
dispatcher.add_handler(ADMINLIST_HANDLER)
