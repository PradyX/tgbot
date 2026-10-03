from typing import Optional

from telegram import Message, Update, Bot, User
from telegram import MessageEntity
from telegram.ext import filters, MessageHandler

from tg_bot import dispatcher
from tg_bot.modules.disable import DisableAbleCommandHandler, DisableAbleRegexHandler
from tg_bot.modules.sql import afk_sql as sql
from tg_bot.modules.users import get_user_id

AFK_GROUP = 7
AFK_REPLY_GROUP = 8


async def afk(update, context):
    bot = context.bot
    args = update.effective_message.text.split(None, 1)
    if len(args) >= 2:
        reason = args[1]
    else:
        reason = ""

    sql.set_afk(update.effective_user.id, reason)
    await update.effective_message.reply_text("{} is now AFK!".format(update.effective_user.first_name))


async def no_longer_afk(update, context):
    bot = context.bot
    user = update.effective_user  # type: Optional[User]

    if not user:  # ignore channels
        return

    res = sql.rm_afk(user.id)
    if res:
        await update.effective_message.reply_text("{} is no longer AFK!".format(update.effective_user.first_name))


async def reply_afk(update, context):
    bot = context.bot
    message = update.effective_message  # type: Optional[Message]
    entities = message.parse_entities([MessageEntity.TEXT_MENTION, MessageEntity.MENTION])
    if message.entities and entities:
        for ent in entities:
            if ent.type == MessageEntity.TEXT_MENTION:
                user_id = ent.user.id
                fst_name = ent.user.first_name

            elif ent.type == MessageEntity.MENTION:
                user_id = await get_user_id(message.text[ent.offset:ent.offset + ent.length])
                if not user_id:
                    # Should never happen, since for a user to become AFK they must have spoken. Maybe changed username?
                    return
                chat = await bot.get_chat(user_id)
                fst_name = chat.first_name

            else:
                return

            if sql.is_afk(user_id):
                valid, reason = sql.check_afk_status(user_id)
                if valid:
                    if not reason:
                        res = "{} is AFK!".format(fst_name)
                    else:
                        res = "{} is AFK! says its because of:\n{}".format(fst_name, reason)
                    await message.reply_text(res)


def __gdpr__(user_id):
    sql.rm_afk(user_id)


__help__ = """
 - /afk <reason>: mark yourself as AFK.
 - brb <reason>: same as the afk command - but not a command.

When marked as AFK, any mentions will be replied to with a message to say you're not available!
"""

__mod_name__ = "AFK"

AFK_HANDLER = DisableAbleCommandHandler("afk", afk)
AFK_REGEX_HANDLER = DisableAbleRegexHandler("(?i)brb", afk, friendly="afk")
NO_AFK_HANDLER = MessageHandler(filters.ALL & filters.ChatType.GROUPS, no_longer_afk)
AFK_REPLY_HANDLER = MessageHandler(filters.Entity(MessageEntity.MENTION) | filters.Entity(MessageEntity.TEXT_MENTION),
                                   reply_afk)

dispatcher.add_handler(AFK_HANDLER, AFK_GROUP)
dispatcher.add_handler(AFK_REGEX_HANDLER, AFK_GROUP)
dispatcher.add_handler(NO_AFK_HANDLER, AFK_GROUP)
dispatcher.add_handler(AFK_REPLY_HANDLER, AFK_REPLY_GROUP)
