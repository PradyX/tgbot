from functools import wraps
from typing import Optional

from tg_bot.modules.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    from telegram import Bot, Update, Message, Chat
    from telegram.constants import ChatType, ParseMode
    from telegram.error import BadRequest, Forbidden
    from telegram.ext import CommandHandler
    from telegram.helpers import escape_markdown

    from tg_bot import dispatcher, LOGGER
    from tg_bot.modules.helper_funcs.chat_status import user_admin
    from tg_bot.modules.sql import log_channel_sql as sql


    def loggable(func):
        @wraps(func)
        async def log_action(update: Update, context, *args, **kwargs):
            result = await func(update, context, *args, **kwargs)
            chat = update.effective_chat  # type: Optional[Chat]
            message = update.effective_message  # type: Optional[Message]
            if result:
                if chat.type == ChatType.SUPERGROUP and chat.username:
                    result += "\n<b>Link:</b> " \
                              "<a href=\"http://telegram.me/{}/{}\">click here</a>".format(chat.username,
                                                                                         message.message_id)
                log_chat = sql.get_chat_log_channel(chat.id)
                if log_chat:
                    await send_log(context.bot, log_chat, chat.id, result)
            elif result == "":
                pass
            else:
                LOGGER.warning("%s was set as loggable, but had no return statement.", func)

            return result

        return log_action


    async def send_log(bot: Bot, log_chat_id: str, orig_chat_id: str, result: str):
        try:
            await bot.send_message(log_chat_id, result, parse_mode=ParseMode.HTML)
        except BadRequest as excp:
            if excp.message == "Chat not found":
                await bot.send_message(orig_chat_id, "This log channel has been deleted - unsetting.")
                sql.stop_chat_logging(orig_chat_id)
            else:
                LOGGER.warning(excp.message)
                LOGGER.warning(result)
                LOGGER.exception("Could not parse")

                await bot.send_message(log_chat_id, result +
                                       "\n\nFormatting has been disabled due to an unexpected error.")


    @user_admin
    async def logging(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]

        log_channel = sql.get_chat_log_channel(chat.id)
        if log_channel:
            log_channel_info = await context.bot.get_chat(log_channel)
            await message.reply_text(
                "This group has all it's logs sent to: {} (`{}`)".format(escape_markdown(log_channel_info.title),
                                                                         log_channel),
                parse_mode=ParseMode.MARKDOWN)

        else:
            await message.reply_text("No log channel has been set for this group!")


    @user_admin
    async def setlog(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]
        if chat.type == ChatType.CHANNEL:
            await message.reply_text("Now, forward the /setlog to the group you want to tie this channel to!")

        elif message.forward_from_chat:
            sql.set_chat_log_channel(chat.id, message.forward_from_chat.id)
            try:
                await message.delete()
            except BadRequest as excp:
                if excp.message == "Message to delete not found":
                    pass
                else:
                    LOGGER.exception("Error deleting message in log channel. Should work anyway though.")

            try:
                await context.bot.send_message(message.forward_from_chat.id,
                                               "This channel has been set as the log channel for {}.".format(
                                                   chat.title or chat.first_name))
            except Forbidden:
                await context.bot.send_message(chat.id, "Successfully set log channel!")

            await context.bot.send_message(chat.id, "Successfully set log channel!")

        else:
            await message.reply_text("The steps to set a log channel are:\n"
                                     " - add bot to the desired channel\n"
                                     " - send /setlog to the channel\n"
                                     " - forward the /setlog to the group\n")


    @user_admin
    async def unsetlog(update, context):
        message = update.effective_message  # type: Optional[Message]
        chat = update.effective_chat  # type: Optional[Chat]

        log_channel = sql.stop_chat_logging(chat.id)
        if log_channel:
            await context.bot.send_message(log_channel, "Channel has been unlinked from {}".format(chat.title))
            await message.reply_text("Log channel has been un-set.")

        else:
            await message.reply_text("No log channel has been set yet!")


    def __stats__():
        return "{} log channels set.".format(sql.num_logchannels())


    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)


    async def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            log_channel_info = await dispatcher.bot.get_chat(log_channel)
            return "This group has all it's logs sent to: {} (`{}`)".format(escape_markdown(log_channel_info.title),
                                                                            log_channel)
        return "No log channel is set for this group!"


    __help__ = """
*Admin only:*
- /logchannel: get log channel info
- /setlog: set the log channel.
- /unsetlog: unset the log channel.

Setting the log channel is done by:
- adding the bot to the desired channel (as an admin!)
- sending /setlog in the channel
- forwarding the /setlog to the group
"""

    __mod_name__ = "Log Channels"

    LOG_HANDLER = CommandHandler("logchannel", logging)
    SET_LOG_HANDLER = CommandHandler("setlog", setlog)
    UNSET_LOG_HANDLER = CommandHandler("unsetlog", unsetlog)

    dispatcher.add_handler(LOG_HANDLER)
    dispatcher.add_handler(SET_LOG_HANDLER)
    dispatcher.add_handler(UNSET_LOG_HANDLER)

else:
    # run anyway if module not loaded
    def loggable(func):
        return func
