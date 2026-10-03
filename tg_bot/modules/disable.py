from typing import Union, List, Optional

from telegram import Update, Chat, User
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, filters
from telegram.helpers import escape_markdown

from tg_bot import dispatcher
from tg_bot.modules.helper_funcs.handlers import CMD_STARTERS, CustomRegexHandler
from tg_bot.modules.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

# If module is due to be loaded, then setup all the magical handlers
if is_module_loaded(FILENAME):
    from tg_bot.modules.helper_funcs.chat_status import user_admin, is_user_admin

    from tg_bot.modules.sql import disable_sql as sql

    DISABLE_CMDS = []
    DISABLE_OTHER = []
    ADMIN_CMDS = []

    class DisableAbleCommandHandler(CommandHandler):
        def __init__(self, command, callback, admin_ok=False, **kwargs):
            # The disabled-command check happens in the callback wrapper: check_update is
            # sync in PTB v22, but verifying admin status requires an (async) API call.
            async def disabled_gate(update, context):
                chat = update.effective_chat  # type: Optional[Chat]
                user = update.effective_user  # type: Optional[User]
                command_name = update.effective_message.text_html.split(None, 1)[0][1:].split('@')[0].lower()

                if sql.is_command_disabled(chat.id, command_name):
                    if not (command_name in ADMIN_CMDS and await is_user_admin(chat, user.id)):
                        return  # command is disabled for this user

                return await callback(update, context)

            super().__init__(command, disabled_gate, **kwargs)
            self.callback = callback
            if isinstance(command, str):
                DISABLE_CMDS.append(command)
                if admin_ok:
                    ADMIN_CMDS.append(command)
            else:
                DISABLE_CMDS.extend(command)
                if admin_ok:
                    ADMIN_CMDS.extend(command)

        def check_update(self, update):
            if super().check_update(update):
                chat = update.effective_chat  # type: Optional[Chat]
                user = update.effective_user  # type: Optional[User]
                # Should be safe since check_update passed.
                command = update.effective_message.text_html.split(None, 1)[0][1:].split('@')[0]

                # disabled, admincmd, user admin
                if sql.is_command_disabled(chat.id, command):
                    return command in ADMIN_CMDS

                # not disabled
                return True

            return False


    class DisableAbleRegexHandler(CustomRegexHandler):
        def __init__(self, pattern, callback, friendly="", **kwargs):
            async def disabled_gate(update, context):
                chat = update.effective_chat
                if sql.is_command_disabled(chat.id, self.friendly):
                    return
                return await callback(update, context)

            super().__init__(pattern, disabled_gate, **kwargs)
            self.callback = callback
            DISABLE_OTHER.append(friendly or pattern)
            self.friendly = friendly or pattern

        def check_update(self, update):
            chat = update.effective_chat
            return super().check_update(update) and not sql.is_command_disabled(chat.id, self.friendly)


    @user_admin
    async def disable(update, context):
        chat = update.effective_chat  # type: Optional[Chat]
        args = context.args
        if len(args) >= 1:
            disable_cmd = args[0]
            if disable_cmd.startswith(CMD_STARTERS):
                disable_cmd = disable_cmd[1:]

            if disable_cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                sql.disable_command(chat.id, disable_cmd)
                await update.effective_message.reply_text("Disabled the use of `{}`".format(disable_cmd),
                                                          parse_mode=ParseMode.MARKDOWN)
            else:
                await update.effective_message.reply_text("That command can't be disabled")

        else:
            await update.effective_message.reply_text("What should I disable?")


    @user_admin
    async def enable(update, context):
        chat = update.effective_chat  # type: Optional[Chat]
        args = context.args
        if len(args) >= 1:
            enable_cmd = args[0]
            if enable_cmd.startswith(CMD_STARTERS):
                enable_cmd = enable_cmd[1:]

            if sql.enable_command(chat.id, enable_cmd):
                await update.effective_message.reply_text("Enabled the use of `{}`".format(enable_cmd),
                                                          parse_mode=ParseMode.MARKDOWN)
            else:
                await update.effective_message.reply_text("Is that even disabled?")

        else:
            await update.effective_message.reply_text("What should I enable?")


    @user_admin
    async def list_cmds(update, context):
        if DISABLE_CMDS + DISABLE_OTHER:
            result = ""
            for cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                result += " - `{}`\n".format(escape_markdown(cmd))
            await update.effective_message.reply_text("The following commands are toggleable:\n{}".format(result),
                                                      parse_mode=ParseMode.MARKDOWN)
        else:
            await update.effective_message.reply_text("No commands can be disabled.")


    # do not async
    def build_curr_disabled(chat_id: Union[str, int]) -> str:
        disabled = sql.get_all_disabled(chat_id)
        if not disabled:
            return "No commands are disabled!"

        result = ""
        for cmd in disabled:
            result += " - `{}`\n".format(escape_markdown(cmd))
        return "The following commands are currently restricted:\n{}".format(result)


    async def commands(update, context):
        chat = update.effective_chat
        await update.effective_message.reply_text(build_curr_disabled(chat.id), parse_mode=ParseMode.MARKDOWN)


    def __stats__():
        return "{} disabled items, across {} chats.".format(sql.num_disabled(), sql.num_chats())


    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)


    def __chat_settings__(chat_id, user_id):
        return build_curr_disabled(chat_id)


    __mod_name__ = "Command disabling"

    __help__ = """
 - /cmds: check the current status of disabled commands

*Admin only:*
 - /enable <cmd name>: enable that command
 - /disable <cmd name>: disable that command
 - /listcmds: list all possible toggleable commands
    """

    DISABLE_HANDLER = CommandHandler("disable", disable, filters=filters.ChatType.GROUPS)
    ENABLE_HANDLER = CommandHandler("enable", enable, filters=filters.ChatType.GROUPS)
    COMMANDS_HANDLER = CommandHandler(["cmds", "disabled"], commands, filters=filters.ChatType.GROUPS)
    TOGGLE_HANDLER = CommandHandler("listcmds", list_cmds, filters=filters.ChatType.GROUPS)

    dispatcher.add_handler(DISABLE_HANDLER)
    dispatcher.add_handler(ENABLE_HANDLER)
    dispatcher.add_handler(COMMANDS_HANDLER)
    dispatcher.add_handler(TOGGLE_HANDLER)

else:
    DisableAbleCommandHandler = CommandHandler
    DisableAbleRegexHandler = CustomRegexHandler
