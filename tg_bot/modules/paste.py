from typing import Optional

import httpx
from telegram import Message
from telegram.constants import MessageLimit
from telegram.ext import CommandHandler

from tg_bot import dispatcher, LOGGER
from tg_bot.modules.disable import DisableAbleCommandHandler

DPASTE_API = "https://dpaste.org/api/"


async def paste(update, context):
    message = update.effective_message  # type: Optional[Message]

    if message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    elif message.text and " " in message.text:
        text = message.text.split(None, 1)[1]
    else:
        await message.reply_text("Reply to a message, or give me some text after the command, to paste it.")
        return

    if not text:
        await message.reply_text("There's no text there to paste!")
        return

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.post(DPASTE_API,
                                    data={"content": text, "syntax": "plain", "expiry_days": "7"})
    except httpx.HTTPError:
        await message.reply_text("The paste service didn't respond - try again later.")
        return

    if res.is_success:
        # API returns the url as a JSON string, e.g. "https://dpaste.org/13LTV"
        paste_url = res.text.strip().strip('"')
        await message.reply_text("Pasted to: {}".format(paste_url))
    else:
        LOGGER.warning("dpaste returned %s", res.status_code)
        await message.reply_text("Failed to create paste - the service may be down.")


async def get_paste_content(update, context):
    message = update.effective_message  # type: Optional[Message]
    args = context.args

    if not args:
        await message.reply_text("Usage: `/getpaste <paste url or id>`", parse_mode="Markdown")
        return

    ref = args[0]
    if ref.startswith("http"):
        paste_url = ref
    else:
        paste_url = "https://dpaste.org/{}".format(ref)

    if not paste_url.endswith(".txt"):
        paste_url += ".txt"

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.get(paste_url)
    except httpx.HTTPError:
        await message.reply_text("Failed to fetch that paste - try again later.")
        return

    if not res.is_success or not res.text:
        await message.reply_text("Couldn't find that paste.")
        return

    text = res.text
    if len(text) > MessageLimit.MAX_TEXT_LENGTH - 100:
        text = text[:MessageLimit.MAX_TEXT_LENGTH - 100] + "\n[... truncated]"
    await message.reply_text("Paste content:\n\n{}".format(text))


__help__ = """
 - /paste: paste text (as a reply, or with text after the command) to dpaste.org
 - /getpaste <url or id>: fetch the content of a paste
"""

__mod_name__ = "Paste"

PASTE_HANDLER = DisableAbleCommandHandler("paste", paste)
GET_PASTE_HANDLER = CommandHandler("getpaste", get_paste_content)

dispatcher.add_handler(PASTE_HANDLER)
dispatcher.add_handler(GET_PASTE_HANDLER)
