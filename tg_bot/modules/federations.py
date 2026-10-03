import html
from typing import Optional

from telegram import Message, Chat, Update, User
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CommandHandler, MessageHandler, filters
from telegram.helpers import mention_html

from tg_bot import dispatcher, LOGGER
from tg_bot.modules.helper_funcs.chat_status import user_admin, bot_admin
from tg_bot.modules.helper_funcs.extraction import extract_user_and_text
from tg_bot.modules.helper_funcs.misc import split_message
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql import federation_sql as sql
from tg_bot.modules.users import get_user_id

FED_ENFORCE_GROUP = -1


async def resolve_user(arg: str):
    if arg.startswith("@"):
        return await get_user_id(arg)
    if arg.isdigit():
        return int(arg)
    return None


async def new_fed(update, context):
    user = update.effective_user
    msg = update.effective_message
    args = context.args

    if not args:
        await msg.reply_text("Usage: `/newfed <federation name>`", parse_mode=ParseMode.MARKDOWN)
        return

    existing = sql.get_fed_by_owner(user.id)
    if existing:
        await msg.reply_text("You already own a federation: *{}* (`{}`).\nYou can delete it with "
                             "`/delfed {}`.".format(html.escape(existing.fed_name), existing.fed_id,
                                                    existing.fed_id),
                             parse_mode=ParseMode.MARKDOWN)
        return

    fed_name = msg.text.split(None, 1)[1]
    fed_id, fed_name = sql.create_fed(user.id, fed_name)
    await msg.reply_text("Federation *{}* has been created!\n"
                         "Fed id: `{}`\n\n"
                         "Add your groups with `/joinfed {}` (as a group admin).".format(
                             html.escape(fed_name), fed_id, fed_id),
                         parse_mode=ParseMode.MARKDOWN)


async def del_fed(update, context):
    user = update.effective_user
    msg = update.effective_message
    args = context.args

    if not args:
        await msg.reply_text("Usage: `/delfed <fed_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    fed_id = args[0]
    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    if fed.owner_id != user.id:
        await msg.reply_text("Only the federation owner can delete the federation.")
        return

    sql.del_fed(fed_id)
    await msg.reply_text("Federation *{}* has been deleted.".format(html.escape(fed.fed_name)),
                         parse_mode=ParseMode.MARKDOWN)


@user_admin
async def join_fed(update, context):
    chat = update.effective_chat
    msg = update.effective_message
    args = context.args

    if chat.type == "private":
        await msg.reply_text("This command only works in groups.")
        return

    if not args:
        await msg.reply_text("Usage: `/joinfed <fed_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    fed_id = args[0]
    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    if not sql.is_fed_admin(fed_id, update.effective_user.id):
        await msg.reply_text("Only federation admins/owners can add groups to a federation.")
        return

    current = sql.get_chat_fed(chat.id)
    if current:
        await msg.reply_text("This chat already belongs to a federation (`{}`). Leave it first with "
                             "`/leavefed`.".format(current))
        return

    sql.join_fed(chat.id, fed_id)
    await msg.reply_text("This chat has joined the federation *{}* (`{}`)!".format(html.escape(fed.fed_name),
                                                                                  fed_id),
                         parse_mode=ParseMode.MARKDOWN)


@user_admin
async def leave_fed(update, context):
    chat = update.effective_chat
    msg = update.effective_message

    if not sql.get_chat_fed(chat.id):
        await msg.reply_text("This chat isn't in a federation.")
        return

    sql.leave_fed(chat.id)
    await msg.reply_text("This chat has left its federation.")


async def chat_fed(update, context):
    chat = update.effective_chat
    msg = update.effective_message

    fed_id = sql.get_chat_fed(chat.id)
    if not fed_id:
        await msg.reply_text("This chat is not in a federation.")
        return

    fed = sql.get_fed(fed_id)
    await msg.reply_text("This chat is part of the federation *{}* (`{}`).".format(
        html.escape(fed.fed_name if fed else "unknown"), fed_id), parse_mode=ParseMode.MARKDOWN)


async def fed_info(update, context):
    msg = update.effective_message
    args = context.args

    if args:
        fed_id = args[0]
    else:
        fed_id = sql.get_chat_fed(update.effective_chat.id)

    if not fed_id:
        await msg.reply_text("Usage: `/fedinfo <fed_id>` (or use it in a federated chat).",
                             parse_mode=ParseMode.MARKDOWN)
        return

    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    chats = sql.get_fed_chats(fed_id)
    admins = sql.get_fed_admins(fed_id)
    bans = sql.get_fban_list(fed_id)

    text = "<b>{}</b> (<code>{}</code>)\n".format(html.escape(fed.fed_name), fed_id)
    text += "<b>Owner:</b> {}\n".format(mention_html(fed.owner_id, "owner"))
    text += "<b>Admins:</b> {}\n".format(", ".join(str(a) for a in admins) if admins else "none")
    text += "<b>Groups:</b> {}\n".format(len(chats))
    text += "<b>Active fban list:</b> {}".format(len(bans))

    await msg.reply_text(text, parse_mode=ParseMode.HTML)


@user_admin
@loggable
async def fban(update, context) -> str:
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    fed_id = sql.get_chat_fed(chat.id)
    if not fed_id:
        await msg.reply_text("This chat is not in a federation, so you can't fban here.")
        return ""

    if not sql.is_fed_admin(fed_id, user.id):
        await msg.reply_text("Only federation admins can fban.")
        return ""

    user_id, reason = await extract_user_and_text(msg, args)
    if not user_id:
        await msg.reply_text("You'll need to either give me a username to fban, or reply to someone to be fbanned.")
        return ""

    if user_id == bot.id:
        await msg.reply_text("I'm not fban-ing myself!")
        return ""

    if sql.is_fed_admin(fed_id, user_id):
        await msg.reply_text("I can't fban a federation admin!")
        return ""

    sql.fban_user(fed_id, user_id, reason=reason, banned_by=user.id)

    failed = []
    banned = 0
    for fed_chat in sql.get_fed_chats(fed_id):
        try:
            await bot.ban_member(int(fed_chat), user_id)
            banned += 1
        except TelegramError:
            failed.append(fed_chat)

    reply = "{} has been fbanned in federation <code>{}</code>.".format(mention_html(user_id, "user"), fed_id)
    if reason:
        reply += "\nReason: {}".format(html.escape(reason))
    if failed:
        reply += "\n\nCould not ban in {} of {} groups (am I admin there?).".format(len(failed),
                                                                                   len(sql.get_fed_chats(fed_id)))
    await msg.reply_text(reply, parse_mode=ParseMode.HTML)

    return "<b>{}:</b>" \
           "\n#FBAN" \
           "\n<b>Admin:</b> {}" \
           "\n<b>User:</b> {} (<code>{}</code>)" \
           "\n<b>Reason:</b> {}" \
           "\nBanned in <code>{}</code> groups.".format(html.escape(chat.title),
                                                        mention_html(user.id, user.first_name),
                                                        mention_html(user_id, "user"), user_id,
                                                        html.escape(reason or "No reason given"), banned)


@user_admin
@loggable
async def unfban(update, context) -> str:
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    fed_id = sql.get_chat_fed(chat.id)
    if not fed_id:
        await msg.reply_text("This chat is not in a federation.")
        return ""

    if not sql.is_fed_admin(fed_id, user.id):
        await msg.reply_text("Only federation admins can unfban.")
        return ""

    user_id, _ = await extract_user_and_text(msg, args)
    if not user_id:
        await msg.reply_text("You'll need to either give me a username to unfban, or reply to someone.")
        return ""

    if not sql.unfban_user(fed_id, user_id):
        await msg.reply_text("That user isn't on the fban list.")
        return ""

    for fed_chat in sql.get_fed_chats(fed_id):
        try:
            await bot.unban_member(int(fed_chat), user_id)
        except TelegramError:
            pass

    await msg.reply_text("{} has been un-fbanned.".format(mention_html(user_id, "user")), parse_mode=ParseMode.HTML)
    return "<b>{}:</b>" \
           "\n#UNFBAN" \
           "\n<b>Admin:</b> {}" \
           "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                        mention_html(user.id, user.first_name),
                                                        mention_html(user_id, "user"), user_id)


@user_admin
async def fed_promote(update, context):
    user = update.effective_user
    msg = update.effective_message
    args = context.args

    if len(args) < 2:
        await msg.reply_text("Usage: `/fedpromote <fed_id> <user id or @username>`", parse_mode=ParseMode.MARKDOWN)
        return

    fed_id = args[0]
    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    if fed.owner_id != user.id:
        await msg.reply_text("Only the federation owner can promote fed admins.")
        return

    target = await resolve_user(args[1])
    if not target:
        await msg.reply_text("I can't find that user - give me an id or @username.")
        return

    sql.set_fed_admin(fed_id, target)
    await msg.reply_text("{} is now a federation admin of <b>{}</b>.".format(mention_html(target, "user"),
                                                                            html.escape(fed.fed_name)),
                         parse_mode=ParseMode.HTML)


@user_admin
async def fed_demote(update, context):
    user = update.effective_user
    msg = update.effective_message
    args = context.args

    if len(args) < 2:
        await msg.reply_text("Usage: `/feddemote <fed_id> <user id or @username>`", parse_mode=ParseMode.MARKDOWN)
        return

    fed_id = args[0]
    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    if fed.owner_id != user.id:
        await msg.reply_text("Only the federation owner can demote fed admins.")
        return

    target = await resolve_user(args[1])
    if not target:
        await msg.reply_text("I can't find that user - give me an id or @username.")
        return

    if sql.rm_fed_admin(fed_id, target):
        await msg.reply_text("{} is no longer a federation admin.".format(mention_html(target, "user")),
                             parse_mode=ParseMode.HTML)
    else:
        await msg.reply_text("That user isn't a federation admin.")


async def fed_admins(update, context):
    msg = update.effective_message
    args = context.args

    fed_id = args[0] if args else sql.get_chat_fed(update.effective_chat.id)
    if not fed_id:
        await msg.reply_text("Usage: `/fedadmins <fed_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    fed = sql.get_fed(fed_id)
    if not fed:
        await msg.reply_text("I can't find that federation.")
        return

    owner_line = "Owner: {}".format(mention_html(fed.owner_id, "owner"))
    admins = sql.get_fed_admins(fed_id)
    admin_lines = [owner_line] + [" - {}".format(mention_html(a, "admin")) for a in admins]
    await msg.reply_text("Admins of <b>{}</b>:\n{}".format(html.escape(fed.fed_name), "\n".join(admin_lines)),
                         parse_mode=ParseMode.HTML)


async def fban_list(update, context):
    msg = update.effective_message
    args = context.args

    fed_id = args[0] if args else sql.get_chat_fed(update.effective_chat.id)
    if not fed_id:
        await msg.reply_text("Usage: `/fbanlist <fed_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    bans = sql.get_fban_list(fed_id)
    if not bans:
        await msg.reply_text("The federation fban list is empty.")
        return

    text = "Fban list for <code>{}</code>:\n".format(fed_id)
    for ban in bans:
        text += " - <code>{}</code>: {}\n".format(ban.user_id, html.escape(ban.reason or "No reason"))

    for chunk in split_message(text):
        await msg.reply_text(chunk, parse_mode=ParseMode.HTML)


async def fed_ban_enforcer(update, context):
    """Ban fbanned users who try to join any federated chat."""
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]
    fed_id = sql.get_chat_fed(chat.id)
    if not fed_id:
        return

    new_members = update.effective_message.new_chat_members
    for mem in new_members:
        ban = sql.get_fban(fed_id, mem.id)
        if ban:
            try:
                await chat.ban_member(mem.id)
                await update.effective_message.reply_text(
                    "{} was banned: they are on this federation's fban list.\nReason: {}".format(
                        mention_html(mem.id, mem.first_name), html.escape(ban.reason or "No reason")),
                    parse_mode=ParseMode.HTML)
            except TelegramError:
                LOGGER.warning("Failed to enforce fban on %s in chat %s", mem.id, chat.id)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    fed_id = sql.get_chat_fed(chat_id)
    if not fed_id:
        return "This chat is not in a federation."
    fed = sql.get_fed(fed_id)
    return "This chat is in the federation *{}* (`{}`), with {} fban-listed users.".format(
        fed.fed_name if fed else "unknown", fed_id, len(sql.get_fban_list(fed_id)))


def __stats__():
    return "{} federations, across {} chats, with {} fban-listed users.".format(
        sql.num_feds(), sql.num_fed_chats(), sql.num_fed_bans())


__help__ = """
Federations let you ban a user in *many groups at once* - one fban, and every group in the federation is \
protected.

*Commands:*
 - /newfed <name>: create your federation (one per user). Get your fed id from the reply.
 - /chatfed: see which federation this chat belongs to.
 - /fedinfo <fed_id>: federation stats.
 - /fedadmins <fed_id>: list federation admins.
 - /fbanlist <fed_id>: list fban-listed users.

*Admin only (group):*
 - /joinfed <fed_id>: add this group to a federation (you must be a fed admin).
 - /leavefed: remove this group from its federation.
 - /fban <userhandle> [reason]: ban a user in every federation group. Works as a reply too.
 - /unfban <userhandle>: remove a user from the fban list and unban them everywhere.

*Federation owner only:*
 - /delfed <fed_id>: delete your federation.
 - /fedpromote <fed_id> <user>: make someone a fed admin.
 - /feddemote <fed_id> <user>: demote a fed admin.
"""

__mod_name__ = "Federations"

NEW_FED_HANDLER = CommandHandler("newfed", new_fed)
DEL_FED_HANDLER = CommandHandler("delfed", del_fed)
JOIN_FED_HANDLER = CommandHandler("joinfed", join_fed, filters=filters.ChatType.GROUPS)
LEAVE_FED_HANDLER = CommandHandler("leavefed", leave_fed, filters=filters.ChatType.GROUPS)
CHAT_FED_HANDLER = CommandHandler("chatfed", chat_fed)
FED_INFO_HANDLER = CommandHandler("fedinfo", fed_info)
FBAN_HANDLER = CommandHandler("fban", fban, filters=filters.ChatType.GROUPS)
UNFBAN_HANDLER = CommandHandler("unfban", unfban, filters=filters.ChatType.GROUPS)
FED_PROMOTE_HANDLER = CommandHandler("fedpromote", fed_promote)
FED_DEMOTE_HANDLER = CommandHandler("feddemote", fed_demote)
FED_ADMINS_HANDLER = CommandHandler("fedadmins", fed_admins)
FBAN_LIST_HANDLER = CommandHandler("fbanlist", fban_list)
FED_ENFORCE_HANDLER = MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, fed_ban_enforcer)

dispatcher.add_handler(NEW_FED_HANDLER)
dispatcher.add_handler(DEL_FED_HANDLER)
dispatcher.add_handler(JOIN_FED_HANDLER)
dispatcher.add_handler(LEAVE_FED_HANDLER)
dispatcher.add_handler(CHAT_FED_HANDLER)
dispatcher.add_handler(FED_INFO_HANDLER)
dispatcher.add_handler(FBAN_HANDLER)
dispatcher.add_handler(UNFBAN_HANDLER)
dispatcher.add_handler(FED_PROMOTE_HANDLER)
dispatcher.add_handler(FED_DEMOTE_HANDLER)
dispatcher.add_handler(FED_ADMINS_HANDLER)
dispatcher.add_handler(FBAN_LIST_HANDLER)
dispatcher.add_handler(FED_ENFORCE_HANDLER, FED_ENFORCE_GROUP)
