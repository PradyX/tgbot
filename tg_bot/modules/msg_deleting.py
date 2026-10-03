import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram.error import BadRequest
from telegram.ext import CommandHandler, filters
from telegram.helpers import mention_html

from tg_bot import dispatcher, LOGGER
from tg_bot.modules.helper_funcs.chat_status import user_admin, can_delete
from tg_bot.modules.log_channel import loggable


@user_admin
@loggable
async def purge(update, context) -> str:
    bot = context.bot
    args = context.args
    msg = update.effective_message  # type: Optional[Message]
    if msg.reply_to_message:
        user = update.effective_user  # type: Optional[User]
        chat = update.effective_chat  # type: Optional[Chat]
        if await can_delete(chat, bot.id):
            message_id = msg.reply_to_message.message_id
            delete_to = msg.message_id - 1
            if args and args[0].isdigit():
                new_del = message_id + int(args[0])
                # No point deleting messages which haven't been written yet.
                if new_del < delete_to:
                    delete_to = new_del

            for m_id in range(delete_to, message_id - 1, -1):  # Reverse iteration over message ids
                try:
                    bot.delete_message(chat.id, m_id)
                except BadRequest as err:
                    if err.message == "Message can't be deleted":
                        await bot.send_message(chat.id, "Cannot delete all messages. The messages may be too old, I might "
                                                  "not have delete rights, or this might not be a supergroup.")

                    elif err.message != "Message to delete not found":
                        LOGGER.exception("Error while purging chat messages.")

            try:
                await msg.delete()
            except BadRequest as err:
                if err.message == "Message can't be deleted":
                    await bot.send_message(chat.id, "Cannot delete all messages. The messages may be too old, I might "
                                              "not have delete rights, or this might not be a supergroup.")

                elif err.message != "Message to delete not found":
                    LOGGER.exception("Error while purging chat messages.")

            await bot.send_message(chat.id, "Purge complete.")
            return "<b>{}:</b>" \
                   "\n#PURGE" \
                   "\n<b>Admin:</b> {}" \
                   "\nPurged <code>{}</code> messages.".format(html.escape(chat.title),
                                                               mention_html(user.id, user.first_name),
                                                               delete_to - message_id)

    else:
        await msg.reply_text("Reply to a message to select where to start purging from.")

    return ""


@user_admin
@loggable
async def del_message(update, context) -> str:
    bot = context.bot
    if update.effective_message.reply_to_message:
        user = update.effective_user  # type: Optional[User]
        chat = update.effective_chat  # type: Optional[Chat]
        if await can_delete(chat, bot.id):
            update.effective_message.reply_to_message.delete()
            await update.effective_message.delete()
            return "<b>{}:</b>" \
                   "\n#DEL" \
                   "\n<b>Admin:</b> {}" \
                   "\nMessage deleted.".format(html.escape(chat.title),
                                               mention_html(user.id, user.first_name))
    else:
        await update.effective_message.reply_text("Whadya want to delete?")

    return ""


__help__ = """
*Admin only:*
 - /del: deletes the message you replied to
 - /purge: deletes all messages between this and the replied to message.
 - /purge <integer X>: deletes the replied message, and X messages following it.
"""

__mod_name__ = "Purges"

DELETE_HANDLER = CommandHandler("del", del_message, filters=filters.ChatType.GROUPS)
PURGE_HANDLER = CommandHandler("purge", purge, filters=filters.ChatType.GROUPS)

dispatcher.add_handler(DELETE_HANDLER)
dispatcher.add_handler(PURGE_HANDLER)
