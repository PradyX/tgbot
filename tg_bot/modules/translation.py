import httpx
from telegram import Update, Bot
from telegram.ext import CommandHandler

from tg_bot import dispatcher

# Open API key
API_KEY = "6ae0c3a0-afdc-4532-a810-82ded0054236"
URL = "http://services.gingersoftware.com/Ginger/correct/json/GingerTheText"


async def translate(update, context):
    if update.effective_message.reply_to_message:
        msg = update.effective_message.reply_to_message

        params = dict(
            lang="US",
            clientVersion="2.0",
            apiKey=API_KEY,
            text=msg.text
        )

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                res = await client.get(URL, params=params)
                data = res.json()
        except (ValueError, httpx.HTTPError):
            await update.effective_message.reply_text(
                "The translation service didn't respond - try again later.")
            return

        changes = data.get('LightGingerTheTextResult') or []
        curr_string = ""

        prev_end = 0

        for change in changes:
            start = change.get('From')
            end = change.get('To') + 1
            suggestions = change.get('Suggestions')
            if suggestions:
                sugg_str = suggestions[0].get('Text')  # should look at this list more
                curr_string += msg.text[prev_end:start] + sugg_str

                prev_end = end

        curr_string += msg.text[prev_end:]
        await update.effective_message.reply_text(curr_string)


__help__ = """
 - /t: while replying to a message, will reply with a grammar corrected version
"""

__mod_name__ = "Translator"


TRANSLATE_HANDLER = CommandHandler('t', translate)

dispatcher.add_handler(TRANSLATE_HANDLER)
