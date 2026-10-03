import html
from typing import Optional, List

import telegram.ext as tg
from telegram import Message, Chat, Update, Bot, User, MessageEntity, ChatPermissions
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.error import BadRequest
from telegram.ext import CommandHandler, MessageHandler, filters
from telegram.helpers import mention_html

import tg_bot.modules.sql.locks_sql as sql
from tg_bot import dispatcher, SUDO_USERS, LOGGER
from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot.modules.helper_funcs.chat_status import can_delete, is_user_admin, user_not_admin, user_admin, \
    bot_can_delete, is_bot_admin
from tg_bot.modules.log_channel import loggable
from tg_bot.modules.sql import users_sql

LOCK_TYPES = {'sticker': filters.Sticker.ALL,
              'audio': filters.AUDIO,
              'voice': filters.VOICE,
              'document': filters.Document.ALL & ~filters.ANIMATION,
              'video': filters.VIDEO,
              'videonote': filters.VIDEO_NOTE,
              'contact': filters.CONTACT,
              'photo': filters.PHOTO,
              'gif': filters.ANIMATION,
              'url': filters.Entity(MessageEntity.URL) | filters.CaptionEntity(MessageEntity.URL),
              'bots': filters.StatusUpdate.NEW_CHAT_MEMBERS,
              'forward': filters.FORWARDED,
              'game': filters.GAME,
              'location': filters.LOCATION,
              }

GIF = filters.ANIMATION
OTHER = filters.GAME | filters.Sticker.ALL | GIF
MEDIA = filters.AUDIO | filters.Document.ALL | filters.VIDEO | filters.VIDEO_NOTE | filters.VOICE | filters.PHOTO
MESSAGES = filters.TEXT | filters.CONTACT | filters.LOCATION | filters.VENUE | filters.COMMAND | MEDIA | OTHER
PREVIEWS = filters.Entity("url")

RESTRICTION_TYPES = {'messages': MESSAGES,
                     'media': MEDIA,
                     'other': OTHER,
                     # 'previews': PREVIEWS, # NOTE: this has been removed cos its useless atm.
                     'all': filters.ALL}

PERM_GROUP = 1
REST_GROUP = 2


class CustomCommandHandler(tg.CommandHandler):
    """Commands are ignored for non-admins while 'messages' are restricted in the chat."""

    def __init__(self, command, callback, **kwargs):
        async def lock_gate(update, context):
            if sql.is_restr_locked(update.effective_chat.id, 'messages') \
                    and not await is_user_admin(update.effective_chat, update.effective_user.id):
                return
            return await callback(update, context)

        super().__init__(command, lock_gate, **kwargs)
        self.callback = callback


tg.CommandHandler = CustomCommandHandler


def build_restr_perms(messages, media, other, previews):
    return ChatPermissions(can_send_messages=messages,
                           can_send_audios=media, can_send_documents=media, can_send_photos=media,
                           can_send_videos=media, can_send_video_notes=media, can_send_voice_notes=media,
                           can_send_other_messages=other, can_send_polls=other,
                           can_add_web_page_previews=previews)


async def restr_members(bot, chat_id, members, messages=False, media=False, other=False, previews=False):
    perms = build_restr_perms(messages, media, other, previews)
    for mem in members:
        if mem.user in SUDO_USERS:
            pass
        try:
            await bot.restrict_chat_member(chat_id, mem.user, permissions=perms)
        except TelegramError:
            pass


async def unrestr_members(bot, chat_id, members, messages=True, media=True, other=True, previews=True):
    perms = build_restr_perms(messages, media, other, previews)
    for mem in members:
        try:
            await bot.restrict_chat_member(chat_id, mem.user, permissions=perms)
        except TelegramError:
            pass


async def locktypes(update, context):
    bot = context.bot
    await update.effective_message.reply_text("\n - ".join(["Locks: "] + list(LOCK_TYPES) + list(RESTRICTION_TYPES)))


@user_admin
@bot_can_delete
@loggable
async def lock(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    message = update.effective_message  # type: Optional[Message]
    if await can_delete(chat, bot.id):
        if len(args) >= 1:
            if args[0] in LOCK_TYPES:
                sql.update_lock(chat.id, args[0], locked=True)
                await message.reply_text("Locked {} messages for all non-admins!".format(args[0]))

                return "<b>{}:</b>" \
                       "\n#LOCK" \
                       "\n<b>Admin:</b> {}" \
                       "\nLocked <code>{}</code>.".format(html.escape(chat.title),
                                                          mention_html(user.id, user.first_name), args[0])

            elif args[0] in RESTRICTION_TYPES:
                sql.update_restriction(chat.id, args[0], locked=True)
                if args[0] == "previews":
                    members = users_sql.get_chat_members(str(chat.id))
                    await restr_members(bot, chat.id, members, messages=True, media=True, other=True)

                await message.reply_text("Locked {} for all non-admins!".format(args[0]))
                return "<b>{}:</b>" \
                       "\n#LOCK" \
                       "\n<b>Admin:</b> {}" \
                       "\nLocked <code>{}</code>.".format(html.escape(chat.title),
                                                          mention_html(user.id, user.first_name), args[0])

            else:
                await message.reply_text("What are you trying to lock...? Try /locktypes for the list of lockables")

    else:
        await message.reply_text("I'm not an administrator, or haven't got delete rights.")

    return ""


@user_admin
@loggable
async def unlock(update, context) -> str:
    bot = context.bot
    args = context.args
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    message = update.effective_message  # type: Optional[Message]
    if await is_user_admin(chat, message.from_user.id):
        if len(args) >= 1:
            if args[0] in LOCK_TYPES:
                sql.update_lock(chat.id, args[0], locked=False)
                await message.reply_text("Unlocked {} for everyone!".format(args[0]))
                return "<b>{}:</b>" \
                       "\n#UNLOCK" \
                       "\n<b>Admin:</b> {}" \
                       "\nUnlocked <code>{}</code>.".format(html.escape(chat.title),
                                                            mention_html(user.id, user.first_name), args[0])

            elif args[0] in RESTRICTION_TYPES:
                sql.update_restriction(chat.id, args[0], locked=False)
                """
                members = users_sql.get_chat_members(chat.id)
                if args[0] == "messages":
                    unrestr_members(bot, chat.id, members, media=False, other=False, previews=False)

                elif args[0] == "media":
                    unrestr_members(bot, chat.id, members, other=False, previews=False)

                elif args[0] == "other":
                    unrestr_members(bot, chat.id, members, previews=False)

                elif args[0] == "previews":
                    unrestr_members(bot, chat.id, members)

                elif args[0] == "all":
                    unrestr_members(bot, chat.id, members, True, True, True, True)
                """
                await message.reply_text("Unlocked {} for everyone!".format(args[0]))

                return "<b>{}:</b>" \
                       "\n#UNLOCK" \
                       "\n<b>Admin:</b> {}" \
                       "\nUnlocked <code>{}</code>.".format(html.escape(chat.title),
                                                            mention_html(user.id, user.first_name), args[0])
            else:
                await message.reply_text("What are you trying to unlock...? Try /locktypes for the list of lockables")

        else:
            await bot.send_message(chat.id, "What are you trying to unlock...?")

    return ""


@user_not_admin
async def del_lockables(update, context):
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]
    message = update.effective_message  # type: Optional[Message]

    for lockable, filter in LOCK_TYPES.items():
        if filter(update) and sql.is_locked(chat.id, lockable) and await can_delete(chat, bot.id):
            if lockable == "bots":
                new_members = update.effective_message.new_chat_members
                for new_mem in new_members:
                    if new_mem.is_bot:
                        if not await is_bot_admin(chat, bot.id):
                            await message.reply_text("I see a bot, and I've been told to stop them joining... "
                                               "but I'm not admin!")
                            return

                        await chat.ban_member(new_mem.id)
                        await message.reply_text("Only admins are allowed to add bots to this chat! Get outta here.")
            else:
                try:
                    await message.delete()
                except BadRequest as excp:
                    if excp.message == "Message to delete not found":
                        pass
                    else:
                        LOGGER.exception("ERROR in lockables")

            break


@user_not_admin
async def rest_handler(update, context):
    bot = context.bot
    msg = update.effective_message  # type: Optional[Message]
    chat = update.effective_chat  # type: Optional[Chat]
    for restriction, filter in RESTRICTION_TYPES.items():
        if filter(update) and sql.is_restr_locked(chat.id, restriction) and await can_delete(chat, bot.id):
            try:
                await msg.delete()
            except BadRequest as excp:
                if excp.message == "Message to delete not found":
                    pass
                else:
                    LOGGER.exception("ERROR in restrictions")
            break


def build_lock_message(chat_id):
    locks = sql.get_locks(chat_id)
    restr = sql.get_restr(chat_id)
    if not (locks or restr):
        res = "There are no current locks in this chat."
    else:
        res = "These are the locks in this chat:"
        if locks:
            res += "\n - sticker = `{}`" \
                   "\n - audio = `{}`" \
                   "\n - voice = `{}`" \
                   "\n - document = `{}`" \
                   "\n - video = `{}`" \
                   "\n - videonote = `{}`" \
                   "\n - contact = `{}`" \
                   "\n - photo = `{}`" \
                   "\n - gif = `{}`" \
                   "\n - url = `{}`" \
                   "\n - bots = `{}`" \
                   "\n - forward = `{}`" \
                   "\n - game = `{}`" \
                   "\n - location = `{}`".format(locks.sticker, locks.audio, locks.voice, locks.document,
                                                 locks.video, locks.videonote, locks.contact, locks.photo, locks.gif, locks.url,
                                                 locks.bots, locks.forward, locks.game, locks.location)
        if restr:
            res += "\n - messages = `{}`" \
                   "\n - media = `{}`" \
                   "\n - other = `{}`" \
                   "\n - previews = `{}`" \
                   "\n - all = `{}`".format(restr.messages, restr.media, restr.other, restr.preview,
                                            all([restr.messages, restr.media, restr.other, restr.preview]))
    return res


@user_admin
async def list_locks(update, context):
    bot = context.bot
    chat = update.effective_chat  # type: Optional[Chat]

    res = build_lock_message(chat.id)

    await update.effective_message.reply_text(res, parse_mode=ParseMode.MARKDOWN)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return build_lock_message(chat_id)


__help__ = """
 - /locktypes: a list of possible locktypes

*Admin only:*
 - /lock <type>: lock items of a certain type (not available in private)
 - /unlock <type>: unlock items of a certain type (not available in private)
 - /locks: the current list of locks in this chat.

Locks can be used to restrict a group's users.
eg:
Locking urls will auto-delete all messages with urls, locking stickers will delete all \
stickers, etc.
Locking bots will stop non-admins from adding bots to the chat.
"""

__mod_name__ = "Locks"

LOCKTYPES_HANDLER = DisableAbleCommandHandler("locktypes", locktypes)
LOCK_HANDLER = CommandHandler("lock", lock, filters=filters.ChatType.GROUPS)
UNLOCK_HANDLER = CommandHandler("unlock", unlock, filters=filters.ChatType.GROUPS)
LOCKED_HANDLER = CommandHandler("locks", list_locks, filters=filters.ChatType.GROUPS)

dispatcher.add_handler(LOCK_HANDLER)
dispatcher.add_handler(UNLOCK_HANDLER)
dispatcher.add_handler(LOCKTYPES_HANDLER)
dispatcher.add_handler(LOCKED_HANDLER)

dispatcher.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, del_lockables), PERM_GROUP)
dispatcher.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, rest_handler), REST_GROUP)
