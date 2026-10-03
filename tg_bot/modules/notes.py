import html
import re
from io import BytesIO
from types import SimpleNamespace
from typing import Optional, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.constants import MessageLimit

MAX_MESSAGE_LENGTH = MessageLimit.MAX_TEXT_LENGTH
from telegram import Message, Update, Bot
from telegram.error import BadRequest
from telegram.ext import CommandHandler, filters
from tg_bot.modules.helper_funcs.handlers import CustomRegexHandler
from telegram.helpers import escape_markdown, mention_html, mention_markdown

import tg_bot.modules.sql.notes_sql as sql
from tg_bot import dispatcher, MESSAGE_DUMP, LOGGER
from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot.modules.helper_funcs.chat_status import user_admin
from tg_bot.modules.helper_funcs.misc import build_keyboard, revert_buttons
from tg_bot.modules.helper_funcs.msg_types import get_note_type
from tg_bot.modules.helper_funcs.string_handling import escape_invalid_curly_brackets
from tg_bot.modules.log_channel import loggable

FILE_MATCHER = re.compile(r"^###file_id(!photo)?###:(.*?)(?:\s|$)")

# Per-user fillings, replaced when a note is opened (Rose-style).
VALID_NOTE_FORMATTERS = ['first', 'last', 'fullname', 'username', 'id', 'mention', 'chatname']

# Per-note delivery tags: {private} forces PM delivery, {noprivate} forces in-chat delivery.
PRIVATE_RE = re.compile(r"\{private\}", re.I)
NOPRIVATE_RE = re.compile(r"\{noprivate\}", re.I)

# Tiny cache so repeated note fetches don't re-fetch the chat just for {chatname}.
_CHAT_CACHE = {}


def _strip_tags(text):
    return NOPRIVATE_RE.sub("", PRIVATE_RE.sub("", text))


def _fill(text, values):
    if not text:
        return text
    return escape_invalid_curly_brackets(text, VALID_NOTE_FORMATTERS).format(**values)


def _md_values(user, chat):
    """Markdown-escaped fillings for the user who opened the note."""
    first_name = user.first_name or "PersonWithNoName"
    fullname = "{} {}".format(first_name, user.last_name) if user.last_name else first_name
    if user.username:
        username = "@" + escape_markdown(user.username)
    else:
        username = mention_markdown(user.id, first_name)
    return dict(first=escape_markdown(first_name),
                last=escape_markdown(user.last_name or first_name),
                fullname=escape_markdown(fullname),
                username=username,
                mention=mention_markdown(user.id, first_name),
                id=user.id,
                chatname=escape_markdown(chat.title or ""))


def _raw_values(user, chat):
    """Unescaped fillings - for button labels and button urls."""
    first_name = user.first_name or "PersonWithNoName"
    fullname = "{} {}".format(first_name, user.last_name) if user.last_name else first_name
    return dict(first=first_name,
                last=user.last_name or first_name,
                fullname=fullname,
                username="@" + user.username if user.username else first_name,
                mention=first_name,
                id=user.id,
                chatname=chat.title or "")


def _render_note(note_text, buttons, user, chat):
    """Apply the fillings to the note text (markdown-escaped) and its buttons (raw)."""
    text = _fill(_strip_tags(note_text), _md_values(user, chat))
    raw = _raw_values(user, chat)
    rows = [SimpleNamespace(name=_fill(btn.name, raw), url=_fill(btn.url, raw),
                            same_line=btn.same_line)
            for btn in buttons]
    return text, rows


def _private_link(bot, chat_id, notename):
    """Deep link used to open a private note in PM; None if the payload would be too long."""
    payload = "note_{}_{}".format(chat_id, notename)
    if len(payload.encode("utf-8")) > 64:
        return None
    return "https://t.me/{}?start={}".format(bot.username, payload)


async def _get_cached_chat(bot, chat_id):
    if chat_id not in _CHAT_CACHE:
        try:
            _CHAT_CACHE[chat_id] = await bot.get_chat(chat_id)
        except BadRequest:
            _CHAT_CACHE[chat_id] = SimpleNamespace(title="")
    return _CHAT_CACHE[chat_id]

ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: dispatcher.bot.send_message,
    sql.Types.BUTTON_TEXT.value: dispatcher.bot.send_message,
    sql.Types.STICKER.value: dispatcher.bot.send_sticker,
    sql.Types.DOCUMENT.value: dispatcher.bot.send_document,
    sql.Types.PHOTO.value: dispatcher.bot.send_photo,
    sql.Types.AUDIO.value: dispatcher.bot.send_audio,
    sql.Types.VOICE.value: dispatcher.bot.send_voice,
    sql.Types.VIDEO.value: dispatcher.bot.send_video
}


async def send_private_redirect(bot, chat_id, notename, link, reply_id):
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📬 Read in PM", url=link)]])
    await bot.send_message(chat_id,
                           "🔒 The note *{}* is private - tap below to read it in PM."
                           .format(escape_markdown(notename)),
                           parse_mode=ParseMode.MARKDOWN,
                           reply_to_message_id=reply_id,
                           reply_markup=keyboard)


async def send_private_note(update, bot, payload):
    """Deliver a note in PM - the target of the private-notes deep link."""
    message = update.effective_message  # type: Optional[Message]
    try:
        chat_id, notename = payload[len("note_"):].split("_", 1)
        chat_id = int(chat_id)
    except ValueError:
        await message.reply_text("This note link is invalid.")
        return

    note = sql.get_note(chat_id, notename)
    if not note:
        await message.reply_text("This note doesn't exist anymore.")
        return

    if note.is_reply:
        try:
            await bot.forward_message(chat_id=update.effective_chat.id,
                                      from_chat_id=MESSAGE_DUMP or chat_id,
                                      message_id=note.value)
        except BadRequest:
            await message.reply_text("This note seems to have been lost - sorry!")
        return

    user = update.effective_user
    chat = await _get_cached_chat(bot, chat_id)
    text, rows = _render_note(note.value, sql.get_buttons(chat_id, notename), user, chat)
    keyboard = InlineKeyboardMarkup(build_keyboard(rows))

    try:
        if note.msgtype in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
            await bot.send_message(update.effective_chat.id, text,
                                   parse_mode=ParseMode.MARKDOWN,
                                   disable_web_page_preview=True,
                                   reply_markup=keyboard)
        else:
            await ENUM_FUNC_MAP[note.msgtype](update.effective_chat.id, note.file, caption=text,
                                              parse_mode=ParseMode.MARKDOWN,
                                              disable_web_page_preview=True,
                                              reply_markup=keyboard)
    except BadRequest:
        await message.reply_text("This note could not be sent, as it is incorrectly formatted.")
        LOGGER.exception("Could not parse private note #%s in chat %s", notename, str(chat_id))


# Do not async
async def get(bot, update, notename, show_none=True, no_format=False):
    chat_id = update.effective_chat.id
    note = sql.get_note(chat_id, notename)
    message = update.effective_message  # type: Optional[Message]

    if note:
        # If we're replying to a message, reply to that message (unless it's an error)
        if message.reply_to_message:
            reply_id = message.reply_to_message.message_id
        else:
            reply_id = message.message_id

        if note.is_reply:
            if MESSAGE_DUMP:
                try:
                    await bot.forward_message(chat_id=chat_id, from_chat_id=MESSAGE_DUMP, message_id=note.value)
                except BadRequest as excp:
                    if excp.message == "Message to forward not found":
                        await message.reply_text("This message seems to have been lost - I'll remove it "
                                           "from your notes list.")
                        sql.rm_note(chat_id, notename)
                    else:
                        raise
            else:
                try:
                    await bot.forward_message(chat_id=chat_id, from_chat_id=chat_id, message_id=note.value)
                except BadRequest as excp:
                    if excp.message == "Message to forward not found":
                        await message.reply_text("Looks like the original sender of this note has deleted "
                                           "their message - sorry! Get your bot admin to start using a "
                                           "message dump to avoid this. I'll remove this note from "
                                           "your saved notes.")
                        sql.rm_note(chat_id, notename)
                    else:
                        raise
        else:
            text = note.value
            keyb = []
            parseMode = ParseMode.MARKDOWN
            buttons = sql.get_buttons(chat_id, notename)
            if no_format:
                parseMode = None
                text += revert_buttons(buttons)
            else:
                # private notes: post a PM link instead of the note itself. {private} and
                # {noprivate} override the chat's /privatenotes setting per note.
                force_private = bool(PRIVATE_RE.search(text))
                force_public = bool(NOPRIVATE_RE.search(text))
                link = _private_link(bot, chat_id, notename)
                if link and (force_private or (sql.get_priv_notes(chat_id) and not force_public)):
                    await send_private_redirect(bot, chat_id, notename, link, reply_id)
                    return

                user = message.from_user or update.effective_user
                chat = await _get_cached_chat(bot, chat_id)
                text, rows = _render_note(text, buttons, user, chat)
                keyb = build_keyboard(rows)

            keyboard = InlineKeyboardMarkup(keyb)

            try:
                if note.msgtype in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
                    await bot.send_message(chat_id, text, reply_to_message_id=reply_id,
                                     parse_mode=parseMode, disable_web_page_preview=True,
                                     reply_markup=keyboard)
                else:
                    await ENUM_FUNC_MAP[note.msgtype](chat_id, note.file, caption=text, reply_to_message_id=reply_id,
                                                parse_mode=parseMode, disable_web_page_preview=True,
                                                reply_markup=keyboard)

            except BadRequest as excp:
                if excp.message == "Entity_mention_user_invalid":
                    await message.reply_text("Looks like you tried to mention someone I've never seen before. If you really "
                                       "want to mention them, forward one of their messages to me, and I'll be able "
                                       "to tag them!")
                elif FILE_MATCHER.match(note.value):
                    await message.reply_text("This note was an incorrectly imported file from another bot - I can't use "
                                       "it. If you really need it, you'll have to save it again. In "
                                       "the meantime, I'll remove it from your notes list.")
                    sql.rm_note(chat_id, notename)
                else:
                    await message.reply_text("This note could not be sent, as it is incorrectly formatted. Ask in "
                                       "@MarieSupport if you can't figure out why!")
                    LOGGER.exception("Could not parse message #%s in chat %s", notename, str(chat_id))
                    LOGGER.warning("Message was: %s", str(note.value))
        return
    elif show_none:
        await message.reply_text("This note doesn't exist")


async def cmd_get(update, context):
    bot = context.bot
    args = context.args
    if len(args) >= 2 and args[1].lower() == "noformat":
        await get(bot, update, args[0], show_none=True, no_format=True)
    elif len(args) >= 1:
        await get(bot, update, args[0], show_none=True)
    else:
        await update.effective_message.reply_text("Get rekt")


async def hash_get(update, context):
    bot = context.bot
    message = update.effective_message.text
    fst_word = message.split()[0]
    no_hash = fst_word[1:]
    await get(bot, update, no_hash, show_none=False)


@user_admin
async def save(update, context):
    bot = context.bot
    chat_id = update.effective_chat.id
    msg = update.effective_message  # type: Optional[Message]

    note_name, text, data_type, content, buttons = get_note_type(msg)

    if data_type is None:
        await msg.reply_text("Dude, there's no note")
        return

    if len(text.strip()) == 0:
        text = note_name

    sql.add_note_to_db(chat_id, note_name, text, data_type, buttons=buttons, file=content)

    await msg.reply_text(
        "Yas! Added {note_name}.\nGet it with /get {note_name}, or #{note_name}".format(note_name=note_name))

    if msg.reply_to_message and msg.reply_to_message.from_user.is_bot:
        if text:
            await msg.reply_text("Seems like you're trying to save a message from a bot. Unfortunately, "
                           "bots can't forward bot messages, so I can't save the exact message. "
                           "\nI'll save all the text I can, but if you want more, you'll have to "
                           "forward the message yourself, and then save it.")
        else:
            await msg.reply_text("Bots are kinda handicapped by telegram, making it hard for bots to "
                           "interact with other bots, so I can't save this message "
                           "like I usually would - do you mind forwarding it and "
                           "then saving that new message? Thanks!")
        return


@user_admin
async def clear(update, context):
    bot = context.bot
    args = context.args
    chat_id = update.effective_chat.id
    if len(args) >= 1:
        notename = args[0]

        if sql.rm_note(chat_id, notename):
            await update.effective_message.reply_text("Successfully removed note.")
        else:
            await update.effective_message.reply_text("That's not a note in my database!")


@user_admin
@loggable
async def privatenotes(update, context) -> str:
    args = context.args
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message  # type: Optional[Message]

    if not args:
        state = sql.get_priv_notes(chat.id)
        await msg.reply_text("Private notes are currently *{}*.\nUse `/privatenotes on|off` to change this."
                             .format("on" if state else "off"), parse_mode=ParseMode.MARKDOWN)
        return ""

    if args[0].lower() in ("on", "yes"):
        sql.set_priv_notes(chat.id, True)
        await msg.reply_text("Notes will now be sent in PM - I'll post a link to them in the chat instead. "
                             "Individual notes can opt out with {{noprivate}}, or opt in with {{private}}.")
        return "<b>{}:</b>" \
               "\n#PRIVATENOTES" \
               "\n<b>Admin:</b> {}" \
               "\nEnabled private notes.".format(html.escape(chat.title),
                                                  mention_html(user.id, user.first_name))

    elif args[0].lower() in ("off", "no"):
        sql.set_priv_notes(chat.id, False)
        await msg.reply_text("Notes will be posted in the chat again.")
        return "<b>{}:</b>" \
               "\n#PRIVATENOTES" \
               "\n<b>Admin:</b> {}" \
               "\nDisabled private notes.".format(html.escape(chat.title),
                                                   mention_html(user.id, user.first_name))

    await msg.reply_text("I understand 'on/yes' or 'off/no' only!")
    return ""


async def list_notes(update, context):
    bot = context.bot
    chat_id = update.effective_chat.id
    note_list = sql.get_all_chat_notes(chat_id)

    msg = "*Notes in chat:*\n"
    for note in note_list:
        note_name = " • `#{}`\n".format(note.name.lower())
        if len(msg) + len(note_name) > MAX_MESSAGE_LENGTH:
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            msg = ""
        msg += note_name

    if msg == "*Notes in chat:*\n":
        await update.effective_message.reply_text("No notes in this chat!")

    elif len(msg) != 0:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def __import_data__(chat_id, data):
    failures = []
    for notename, notedata in data.get('extra', {}).items():
        match = FILE_MATCHER.match(notedata)

        if match:
            failures.append(notename)
            notedata = notedata[match.end():].strip()
            if notedata:
                sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)
        else:
            sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)

    if failures:
        with BytesIO(str.encode("\n".join(failures))) as output:
            output.name = "failed_imports.txt"
            await dispatcher.bot.send_document(chat_id, document=output, filename="failed_imports.txt",
                                         caption="These files/photos failed to import due to originating "
                                                 "from another bot. This is a telegram API restriction, and can't "
                                                 "be avoided. Sorry for the inconvenience!")


def __stats__():
    return "{} notes, across {} chats.".format(sql.num_notes(), sql.num_chats())


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    notes = sql.get_all_chat_notes(chat_id)
    return "There are `{}` notes in this chat.\nPrivate notes are `{}`.".format(
        len(notes), "on" if sql.get_priv_notes(chat_id) else "off")


__help__ = """
 - /get <notename>: get the note with this notename
 - #<notename>: same as /get
 - /notes or /saved: list all saved notes in this chat

If you would like to retrieve the contents of a note without any formatting, use `/get <notename> noformat`. This can \
be useful when updating a current note.

*Fillings:* notes support per-user variables, filled in with the user who opened the note:
 - `{{first}}`, `{{last}}`, `{{fullname}}`, `{{username}}`, `{{mention}}`, `{{id}}`, `{{chatname}}`
Each variable MUST be surrounded by `{{}}`. Fillings work in the note text *and* in button names/urls, so you can \
e.g. deep link to a user with `[profile](buttonurl:https://t.me/somebot?start={{id}})`.

*Private notes:* with `/privatenotes on`, notes are sent to the user's PM instead of the chat (a button is posted \
instead). Add `{{private}}` to a note to force PM delivery even when privatenotes are off, or `{{noprivate}}` to \
force it into the chat even when they're on.

*Admin only:*
 - /save <notename> <notedata>: saves notedata as a note with name notename
A button can be added to a note by using standard markdown link syntax - the link should just be prepended with a \
`buttonurl:` section, as such: `[somelink](buttonurl:example.com)`. Check /markdownhelp for more info.
 - /save <notename>: save the replied message as a note with name notename
 - /clear <notename>: clear note with this name
 - /privatenotes <on/off>: enable or disable private notes for this chat.
"""

__mod_name__ = "Notes"

GET_HANDLER = CommandHandler("get", cmd_get)
HASH_GET_HANDLER = CustomRegexHandler(r"^#[^\s]+", hash_get)

SAVE_HANDLER = CommandHandler("save", save)
DELETE_HANDLER = CommandHandler("clear", clear)
PRIV_NOTES_HANDLER = CommandHandler("privatenotes", privatenotes, filters=filters.ChatType.GROUPS)

LIST_HANDLER = DisableAbleCommandHandler(["notes", "saved"], list_notes, admin_ok=True)

dispatcher.add_handler(GET_HANDLER)
dispatcher.add_handler(SAVE_HANDLER)
dispatcher.add_handler(LIST_HANDLER)
dispatcher.add_handler(DELETE_HANDLER)
dispatcher.add_handler(PRIV_NOTES_HANDLER)
dispatcher.add_handler(HASH_GET_HANDLER)
