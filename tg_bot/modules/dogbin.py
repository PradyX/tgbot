import html
import json
import random

from typing import Optional, List

import requests
from telegram import Message, Chat, Update, Bot, MessageEntity
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, filters

from tg_bot import dispatcher
from tg_bot.modules.disable import DisableAbleCommandHandler

BASE_URL = 'https://del.dog'

async def paste(update, context):
    bot = context.bot
    args = context.args
    message = update.effective_message

    if message.reply_to_message:
        data = message.reply_to_message.text
    elif len(args) >= 1:
        data = message.text.split(None, 1)[1]
    else:
        await message.reply_text("What am I supposed to do with this?!")
        return

    r = requests.post(f'{BASE_URL}/documents', data=data)

    if r.status_code == 404:
        await update.effective_message.reply_text('Failed to reach dogbin')
        r.raise_for_status()

    res = r.json()

    if r.status_code != 200:
        await update.effective_message.reply_text(res['message'])
        r.raise_for_status()

    key = res['key']
    if res['isUrl']:
        reply = f'Shortened URL: {BASE_URL}/{key}\nYou can view stats, etc. [here]({BASE_URL}/v/{key})'
    else:
        reply = f'{BASE_URL}/{key}'
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

async def get_paste_content(update, context):
    bot = context.bot
    args = context.args
    message = update.effective_message

    if len(args) >= 1:
        key = args[0]
    else:
        await message.reply_text("Please supply a paste key!")
        return

    format_normal = f'{BASE_URL}/'
    format_view = f'{BASE_URL}/v/'

    if key.startswith(format_view):
        key = key[len(format_view):]
    elif key.startswith(format_normal):
        key = key[len(format_normal):]

    r = requests.get(f'{BASE_URL}/raw/{key}')

    if r.status_code != 200:
        try:
            res = r.json()
            await update.effective_message.reply_text(res['message'])
        except Exception:
            if r.status_code == 404:
                await update.effective_message.reply_text('Failed to reach dogbin')
            else:
                await update.effective_message.reply_text('Unknown error occured')
        r.raise_for_status()

    await update.effective_message.reply_text(r.text)

async def get_paste_stats(update, context):
    bot = context.bot
    args = context.args
    message = update.effective_message

    if len(args) >= 1:
        key = args[0]
    else:
        await message.reply_text("Please supply a paste key!")
        return

    format_normal = f'{BASE_URL}/'
    format_view = f'{BASE_URL}/v/'

    if key.startswith(format_view):
        key = key[len(format_view):]
    elif key.startswith(format_normal):
        key = key[len(format_normal):]

    r = requests.get(f'{BASE_URL}/documents/{key}')

    if r.status_code != 200:
        try:
            res = r.json()
            await update.effective_message.reply_text(res['message'])
        except Exception:
            if r.status_code == 404:
                await update.effective_message.reply_text('Failed to reach dogbin')
            else:
                await update.effective_message.reply_text('Unknown error occured')
        r.raise_for_status()

    document = r.json()['document']
    key = document['_id']
    views = document['viewCount']
    reply = f'Stats for **[/{key}]({BASE_URL}/{key})**:\nViews: `{views}`'
    await update.effective_message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


__help__ = """
 - /paste: Create a paste or a shortened url using [dogbin](https://del.dog)
 - /getpaste: Get the content of a paste or shortened url from [dogbin](https://del.dog)
 - /pastestats: Get stats of a paste or shortened url from [dogbin](https://del.dog)
"""

__mod_name__ = "dogbin"

PASTE_HANDLER = DisableAbleCommandHandler("paste", paste)
GET_PASTE_HANDLER = DisableAbleCommandHandler("getpaste", get_paste_content)
PASTE_STATS_HANDLER = DisableAbleCommandHandler("pastestats", get_paste_stats)

dispatcher.add_handler(PASTE_HANDLER)
dispatcher.add_handler(GET_PASTE_HANDLER)
dispatcher.add_handler(PASTE_STATS_HANDLER) 