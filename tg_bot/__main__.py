import datetime
import importlib
import re
from functools import wraps
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError, ChatMigrated, TelegramError
from telegram.ext import (CommandHandler, MessageHandler, CallbackQueryHandler, TypeHandler,
                          ApplicationHandlerStop, filters)
from telegram.helpers import escape_markdown

from tg_bot import application, dispatcher, TOKEN, WEBHOOK, SUDO_USERS, OWNER_ID, DONATION_LINK, CERT_PATH, PORT, URL, \
    LOGGER, ALLOW_EXCL
# needed to dynamically load modules
# NOTE: Module order is not guaranteed, specify that in the config file!
from tg_bot.modules import ALL_MODULES
from tg_bot.modules.helper_funcs.chat_status import is_user_admin
from tg_bot.modules.helper_funcs.misc import paginate_modules

IMPORTED = {}
MIGRATEABLE = []
HELPABLE = {}
STATS = []
USER_INFO = []
DATA_IMPORT = []
DATA_EXPORT = []

CHAT_SETTINGS = {}
USER_SETTINGS = {}

GDPR = []

for module_name in ALL_MODULES:
    imported_module = importlib.import_module("tg_bot.modules." + module_name)
    if not hasattr(imported_module, "__mod_name__"):
        imported_module.__mod_name__ = imported_module.__name__

    if not imported_module.__mod_name__.lower() in IMPORTED:
        IMPORTED[imported_module.__mod_name__.lower()] = imported_module
    else:
        raise Exception("Can't have two modules with the same name! Please change one")

    if hasattr(imported_module, "__help__") and imported_module.__help__:
        HELPABLE[imported_module.__mod_name__.lower()] = imported_module

    # Chats to migrate on chat_migrated events
    if hasattr(imported_module, "__migrate__"):
        MIGRATEABLE.append(imported_module)

    if hasattr(imported_module, "__stats__"):
        STATS.append(imported_module)

    if hasattr(imported_module, "__gdpr__"):
        GDPR.append(imported_module)

    if hasattr(imported_module, "__user_info__"):
        USER_INFO.append(imported_module)

    if hasattr(imported_module, "__import_data__"):
        DATA_IMPORT.append(imported_module)

    if hasattr(imported_module, "__export_data__"):
        DATA_EXPORT.append(imported_module)

    if hasattr(imported_module, "__chat_settings__"):
        CHAT_SETTINGS[imported_module.__mod_name__.lower()] = imported_module

    if hasattr(imported_module, "__user_settings__"):
        USER_SETTINGS[imported_module.__mod_name__.lower()] = imported_module


async def call_maybe_async(func, *args, **kwargs):
    """Call a module settings hook; hooks may be sync or async."""
    res = func(*args, **kwargs)
    if hasattr(res, "__await__"):
        res = await res
    return res


def restricted(func):
    """Restrict usage of func to allowed users only and replies if necessary"""

    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        chat_type = update.effective_chat.type
        if chat_type == "private" and user_id not in SUDO_USERS:
            LOGGER.warning("Unauthorized access denied for %s.", user_id)
            await update.effective_message.reply_text('You are not allowed to PM me, ask BOT OWNER for access.')
            return  # quit function
        return await func(update, context, *args, **kwargs)

    return wrapped


def _help_strings() -> str:
    return """
Hey there! My name is *{}*.
I'm a modular group management bot with a few fun extras! Have a look at the following for an idea of some of \
the things I can help you with.

*Main* commands available:
 - /start: start the bot
 - /help: PM's you this message.
 - /help <module name>: PM's you info about that module.
 - /donate: information about how to donate!
 - /settings:
   - in PM: will send you your settings for all supported modules.
   - in a group: will redirect you to pm, with all that chat's settings.

{}
And the following:
""".format(dispatcher.bot.first_name, "" if not ALLOW_EXCL else "\nAll commands can either be used with / or !.\n")


PM_START_TEXT = """
Hi {}, my name is {}! If you have any questions on how to use me, read /help.

I'm a group manager bot built in python3, using the python-telegram-bot library, and am fully opensource; \
you can find what makes me tick [here](github.com/PradyX/tgbot)! and the original source [here](github.com/PaulSonOfLars/tgbot)!

Feel free to submit pull requests on github with any bugs, questions \
or feature requests you might have :)

You can find the list of available commands with /help.
"""

DONATE_STRING = """Heya, glad to hear you want to donate!
We currently don't take donations but you can donate to original creator.
It took lots of work for my original creator to get me to where I am now, and every donation helps \
motivate him to make me even better. All the donation money will go to a better VPS to host me, and/or beer \
(see his bio!). He's just a poor student, so every little helps!
There are two ways of paying him; [PayPal](paypal.me/PaulSonOfLars), or [Monzo](monzo.me/paulnionvestergaardlarsen)."""


async def send_help(chat_id, text, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
    await dispatcher.bot.send_message(chat_id=chat_id,
                                      text=text,
                                      parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=keyboard)


@restricted
async def start(update: Update, context):
    if update.effective_chat.type == "private":
        args = context.args
        if len(args) >= 1:
            if args[0].lower() == "help":
                await send_help(update.effective_chat.id, _help_strings())

            elif args[0].lower().startswith("stngs_"):
                match = re.match("stngs_(.*)", args[0].lower())
                chat = await dispatcher.bot.get_chat(match.group(1))

                if await is_user_admin(chat, update.effective_user.id):
                    await send_settings(match.group(1), update.effective_user.id, False)
                else:
                    await send_settings(match.group(1), update.effective_user.id, True)

            elif args[0][1:].isdigit() and "rules" in IMPORTED:
                await IMPORTED["rules"].send_rules(update, args[0], from_pm=True)

        else:
            first_name = update.effective_user.first_name
            await update.effective_message.reply_text(
                PM_START_TEXT.format(escape_markdown(first_name), escape_markdown(context.bot.first_name), OWNER_ID),
                parse_mode=ParseMode.MARKDOWN)
    else:
        await update.effective_message.reply_text("Yo, whadup?")


async def error_callback(update: object, context):
    error = context.error
    try:
        raise error
    except BadRequest:
        LOGGER.warning("BadRequest caught: %s", error)
    except TimedOut:
        LOGGER.warning("TimedOut caught")
    except NetworkError:
        LOGGER.warning("NetworkError caught")
    except ChatMigrated as err:
        LOGGER.warning("ChatMigrated: %s", err)
    except TelegramError:
        LOGGER.warning("TelegramError: %s", error)


async def help_button(update: Update, context):
    query = update.callback_query
    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)
    try:
        if mod_match:
            module = mod_match.group(1)
            text = "Here is the help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
                   + HELPABLE[module].__help__
            await query.message.reply_text(text=text,
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(
                                               [[InlineKeyboardButton(text="Back", callback_data="help_back")]]))

        elif prev_match:
            curr_page = int(prev_match.group(1))
            await query.message.reply_text(_help_strings(),
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(
                                               paginate_modules(curr_page - 1, HELPABLE, "help")))

        elif next_match:
            next_page = int(next_match.group(1))
            await query.message.reply_text(_help_strings(),
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(
                                               paginate_modules(next_page + 1, HELPABLE, "help")))

        elif back_match:
            await query.message.reply_text(text=_help_strings(),
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help")))

        # ensure no spinny white circle
        await context.bot.answer_callback_query(query.id)
        await query.message.delete()
    except BadRequest as excp:
        if excp.message == "Message is not modified":
            pass
        elif excp.message == "Query_id_invalid":
            pass
        elif excp.message == "Message can't be deleted":
            pass
        else:
            LOGGER.exception("Exception in help buttons. %s", str(query.data))


async def get_help(update: Update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    args = update.effective_message.text.split(None, 1)

    # ONLY send help in PM
    if chat.type != ChatType.PRIVATE:

        await update.effective_message.reply_text("Contact me in PM to get the list of possible commands.",
                                                  reply_markup=InlineKeyboardMarkup(
                                                      [[InlineKeyboardButton(text="Help",
                                                                             url="t.me/{}?start=help".format(
                                                                                 context.bot.username))]]))
        return

    elif len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
        module = args[1].lower()
        text = "Here is the available help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
               + HELPABLE[module].__help__
        await send_help(chat.id, text, InlineKeyboardMarkup([[InlineKeyboardButton(text="Back",
                                                                                  callback_data="help_back")]]))

    else:
        await send_help(chat.id, _help_strings())


async def send_settings(chat_id, user_id, user=False):
    if user:
        if USER_SETTINGS:
            settings = "\n\n".join(
                "*{}*:\n{}".format(mod.__mod_name__, await call_maybe_async(mod.__user_settings__, user_id)) for
                mod in USER_SETTINGS.values())
            await dispatcher.bot.send_message(user_id, "These are your current settings:" + "\n\n" + settings,
                                              parse_mode=ParseMode.MARKDOWN)

        else:
            await dispatcher.bot.send_message(user_id,
                                              "Seems like there aren't any user specific settings available :'(",
                                              parse_mode=ParseMode.MARKDOWN)

    else:
        if CHAT_SETTINGS:
            chat_name = (await dispatcher.bot.get_chat(chat_id)).title
            await dispatcher.bot.send_message(user_id,
                                              text="Which module would you like to check {}'s settings for?".format(
                                                  chat_name),
                                              reply_markup=InlineKeyboardMarkup(
                                                  paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)))
        else:
            await dispatcher.bot.send_message(user_id,
                                              "Seems like there aren't any chat settings available :'(\nSend this "
                                              "in a group chat you're admin in to find its current settings!",
                                              parse_mode=ParseMode.MARKDOWN)


async def settings_button(update: Update, context):
    query = update.callback_query
    user = update.effective_user
    mod_match = re.match(r"stngs_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"stngs_prev\((.+?),(.+?)\)", query.data)
    next_match = re.match(r"stngs_next\((.+?),(.+?)\)", query.data)
    back_match = re.match(r"stngs_back\((.+?)\)", query.data)
    try:
        if mod_match:
            chat_id = mod_match.group(1)
            module = mod_match.group(2)
            chat = await context.bot.get_chat(chat_id)
            text = "*{}* has the following settings for the *{}* module:\n\n".format(escape_markdown(chat.title),
                                                                                   CHAT_SETTINGS[
                                                                                       module].__mod_name__) + \
                   await call_maybe_async(CHAT_SETTINGS[module].__chat_settings__, chat_id, user.id)
            await query.message.reply_text(text=text,
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(
                                               [[InlineKeyboardButton(text="Back",
                                                                      callback_data="stngs_back({})".format(
                                                                          chat_id))]]))

        elif prev_match:
            chat_id = prev_match.group(1)
            curr_page = int(prev_match.group(2))
            chat = await context.bot.get_chat(chat_id)
            await query.message.reply_text("Hi there! There are quite a few settings for {} - go ahead and pick what "
                                           "you're interested in.".format(chat.title),
                                           reply_markup=InlineKeyboardMarkup(
                                               paginate_modules(curr_page - 1, CHAT_SETTINGS, "stngs",
                                                                chat=chat_id)))

        elif next_match:
            chat_id = next_match.group(1)
            next_page = int(next_match.group(2))
            chat = await context.bot.get_chat(chat_id)
            await query.message.reply_text("Hi there! There are quite a few settings for {} - go ahead and pick what "
                                           "you're interested in.".format(chat.title),
                                           reply_markup=InlineKeyboardMarkup(
                                               paginate_modules(next_page + 1, CHAT_SETTINGS, "stngs",
                                                                chat=chat_id)))

        elif back_match:
            chat_id = back_match.group(1)
            chat = await context.bot.get_chat(chat_id)
            await query.message.reply_text(text="Hi there! There are quite a few settings for {} - go ahead and pick "
                                                "what you're interested in.".format(escape_markdown(chat.title)),
                                           parse_mode=ParseMode.MARKDOWN,
                                           reply_markup=InlineKeyboardMarkup(
                                               paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)))

        # ensure no spinny white circle
        await context.bot.answer_callback_query(query.id)
        await query.message.delete()
    except BadRequest as excp:
        if excp.message == "Message is not modified":
            pass
        elif excp.message == "Query_id_invalid":
            pass
        else:
            LOGGER.exception("Exception in settings buttons. %s", str(query.data))


async def get_settings(update: Update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]

    # ONLY send settings in PM
    if chat.type != ChatType.PRIVATE:
        if await is_user_admin(chat, user.id):
            text = "Click here to get this chat's settings, as well as yours."
            await msg.reply_text(text,
                                 reply_markup=InlineKeyboardMarkup(
                                     [[InlineKeyboardButton(text="Settings",
                                                            url="t.me/{}?start=stngs_{}".format(
                                                                context.bot.username, chat.id))]]))
    else:
        await send_settings(chat.id, user.id, True)


async def donate(update: Update, context):
    user = update.effective_message.from_user
    chat = update.effective_chat  # type: Optional[Chat]

    if chat.type == "private":
        await update.effective_message.reply_text(DONATE_STRING, parse_mode=ParseMode.MARKDOWN,
                                                  disable_web_page_preview=True)

        if OWNER_ID != 254318997 and DONATION_LINK:
            await update.effective_message.reply_text("You can also donate to the person currently running me "
                                                      "[here]({})".format(DONATION_LINK),
                                                      parse_mode=ParseMode.MARKDOWN)

    else:
        try:
            await context.bot.send_message(user.id, DONATE_STRING, parse_mode=ParseMode.MARKDOWN,
                                           disable_web_page_preview=True)

            await update.effective_message.reply_text("I've PM'ed you about donating to my creator!")
        except NetworkError:
            await update.effective_message.reply_text("Contact me in PM first to get donation information.")


async def migrate_chats(update: Update, context):
    msg = update.effective_message  # type: Optional[Message]
    if msg.migrate_to_chat_id:
        old_chat = update.effective_chat.id
        new_chat = msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old_chat = msg.migrate_from_chat_id
        new_chat = update.effective_chat.id
    else:
        return

    LOGGER.info("Migrating from %s, to %s", str(old_chat), str(new_chat))
    for mod in MIGRATEABLE:
        mod.__migrate__(old_chat, new_chat)

    LOGGER.info("Successfully migrated!")
    raise ApplicationHandlerStop


CHATS_CNT = {}
CHATS_TIME = {}


async def rate_limit_check(update: Update, context):
    """Drop excess updates (>10/sec per chat) to stop floods from locking up the bot."""
    if not update.effective_chat:
        return

    now = datetime.datetime.utcnow()
    cnt = CHATS_CNT.get(update.effective_chat.id, 0)

    t = CHATS_TIME.get(update.effective_chat.id, datetime.datetime(1970, 1, 1))
    if t and now > t + datetime.timedelta(0, 1):
        CHATS_TIME[update.effective_chat.id] = now
        cnt = 0
    else:
        cnt += 1

    if cnt > 10:
        raise ApplicationHandlerStop

    CHATS_CNT[update.effective_chat.id] = cnt


def main():
    start_handler = CommandHandler("start", start)

    help_handler = CommandHandler("help", get_help)
    help_callback_handler = CallbackQueryHandler(help_button, pattern=r"help_")

    settings_handler = CommandHandler("settings", get_settings)
    settings_callback_handler = CallbackQueryHandler(settings_button, pattern=r"stngs_")

    donate_handler = CommandHandler("donate", donate)
    migrate_handler = MessageHandler(filters.StatusUpdate.MIGRATE, migrate_chats)

    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(help_handler)
    dispatcher.add_handler(settings_handler)
    dispatcher.add_handler(help_callback_handler)
    dispatcher.add_handler(settings_callback_handler)
    dispatcher.add_handler(migrate_handler)
    dispatcher.add_handler(donate_handler)

    dispatcher.add_error_handler(error_callback)

    # antiflood processor - runs before every other handler
    dispatcher.add_handler(TypeHandler(filters.ALL, rate_limit_check), -100)

    if WEBHOOK:
        LOGGER.info("Using webhooks.")
        application.run_webhook(listen="127.0.0.1",
                                port=PORT,
                                url_path=TOKEN,
                                webhook_url=URL + TOKEN,
                                cert=CERT_PATH)

    else:
        LOGGER.info("Using long polling.")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == '__main__':
    LOGGER.info("Successfully loaded modules: " + str(ALL_MODULES))
    main()
