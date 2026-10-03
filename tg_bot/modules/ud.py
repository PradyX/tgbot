from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot import dispatcher

from requests import get


async def ud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    text = message.text[len('/ud '):]
    try:
        results = get(f'http://api.urbandictionary.com/v0/define?term={text}', timeout=10).json()
    except ValueError:
        await message.reply_text("Urban dictionary didn't respond - try again later.")
        return

    if not results.get("list"):
        await message.reply_text("No results found for that term.")
        return

    top = results["list"][0]
    reply_text = f'*{text}*\n\n{top["definition"]}\n\n_{top["example"]}_'
    await message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)


__help__ = """
 - /ud:{word} Type the word or expression you want to search use. like /ud telegram Word: Telegram Definition: A once-popular system of telecommunications, in which the sender would contact the telegram service and speak their [message] over the [phone]. The person taking the message would then send it, via a teletype machine, to a telegram office near the receiver's [address]. The message would then be hand-delivered to the addressee. From 1851 until it discontinued the service in 2006, Western Union was the best-known telegram service in the world.
"""

__mod_name__ = "Urban dictionary"

ud_handle = DisableAbleCommandHandler("ud", ud)

dispatcher.add_handler(ud_handle)
