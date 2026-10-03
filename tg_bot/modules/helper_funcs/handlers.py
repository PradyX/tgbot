import telegram.ext as tg
from telegram import Update
from telegram.ext import filters

CMD_STARTERS = ('/', '!')


class CustomCommandHandler(tg.CommandHandler):
    """Command handler that (optionally) also accepts "!" as command starter."""

    def __init__(self, command, callback, **kwargs):
        if "admin_ok" in kwargs:
            del kwargs["admin_ok"]
        super().__init__(command, callback, **kwargs)

    def check_update(self, update):
        if isinstance(update, Update) and update.effective_message:
            message = update.effective_message

            if message.text and len(message.text) > 1:
                fst_word = message.text_html.split(None, 1)[0]
                if len(fst_word) > 1 and any(fst_word.startswith(start) for start in CMD_STARTERS):
                    command = fst_word[1:].split('@')
                    command.append(message.get_bot().username)  # in case the command was sent without a username
                    if self.filters is None:
                        res = True
                    elif isinstance(self.filters, list):
                        res = any(func(message) for func in self.filters)
                    else:
                        res = self.filters(message)

                    return res and (command[0].lower() in self.commands
                                    and command[1].lower() == message.get_bot().username.lower())

            return False
        return None


class CustomRegexHandler(tg.MessageHandler):
    """MessageHandler that behaves like the old RegexHandler(pattern, callback) API."""

    def __init__(self, pattern, callback, friendly="", **kwargs):
        super().__init__(filters.Regex(pattern), callback, **kwargs)
