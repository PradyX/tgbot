# tgbot

A modular Telegram group-management bot, originally based on [Marie](https://t.me/BanhammerMarie_bot)
([PaulSonOfLars/tgbot](https://github.com/PaulSonOfLars/tgbot)), and modernized with features inspired by
[Rose](https://t.me/MissRose_bot).

Runs on **Python 3.10+** with the [python-telegram-bot **v22**](https://github.com/python-telegram-bot/python-telegram-bot)
async API and **SQLAlchemy 2.x** (PostgreSQL in production, SQLite for local development).

Everything is modular: drop a `.py` file into `tg_bot/modules/` and it is loaded automatically, with its help text
merged into `/help`.

---

## Features

**Moderation:** bans, temp-bans, kicks, mutes, temp-mutes, warns with configurable actions
(`/warnmode ban|kick|mute`), word blacklists with modes (`/blacklistmode delete|warn|mute|kick|ban`),
locks and restrictions, anti-flood, purges (`/purge`, `/purge <msgid>`, `/del`), global bans (with optional
[Combot Anti-Spam / CAS](https://cas.chat) enforcement), reporting to admins.

**Federations (Rose-style):** ban a user across *many groups at once* — `/newfed`, `/joinfed`, `/fban`, fed admins,
automatic fban enforcement when a banned user joins any federated group.

**Group configuration:** welcome/goodbye messages with buttons and media, rules, notes with buttons,
custom filters with buttons, per-command disable/enable, log channels.

**Admin tools:** promote with custom titles (`/promote <user> <title>`), demote, pin/unpin,
`/setgtitle`, `/setgdesc`, invite links, admin list.

**Extras:** AFK, userinfo/bios, stickers (`/kang`), reactions, `/paste` (dpaste.org), urban dictionary,
RSS feeds, sed, backups/restore.

---

## Setup guide

### Quick install (Linux server)

An interactive installer does everything below — dependencies, venv, database, configuration, and an optional
systemd service — while asking for your bot token and settings:

```bash
git clone https://github.com/PradyX/tgbot.git
cd tgbot
./scripts/setup_linux.sh
```

Use `./scripts/setup_linux.sh --dry-run` to preview the steps without changing anything. Manual setup below.

### 1. Prerequisites

- **Python 3.10 or newer** (3.10–3.14 all work; the bot is developed and tested on 3.14).
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (`/newbot`).
- Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot)).
- **PostgreSQL** for production (SQLite works out of the box for development — see step 4).

### 2. Get the code and install dependencies

```bash
git clone https://github.com/PradyX/tgbot.git
cd tgbot

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Set up the database

**PostgreSQL (recommended for production):**

```bash
sudo apt-get update && sudo apt-get install postgresql   # debian/ubuntu

sudo su - postgres
createuser -P -s -e YOUR_USER          # choose a password when asked
createdb -O YOUR_USER YOUR_DB_NAME
exit
```

Your database URI will be:

```
postgresql://YOUR_USER:YOUR_PASSWORD@localhost:5432/YOUR_DB_NAME
```

**SQLite (development):** no setup needed — just use `sqlite:///dev.db` as your database URI.

All tables are created automatically on first start.

### 4. Configure the bot

The recommended way is a `tg_bot/config.py` file (it is git-ignored). Extend the sample config so upgrades keep
working:

```python
# tg_bot/config.py
from tg_bot.sample_config import Config


class Development(Config):
    OWNER_ID = 254318997            # your telegram user ID (integer)
    OWNER_USERNAME = "your_username"
    API_KEY = "your bot api key"    # from @BotFather
    SQLALCHEMY_DATABASE_URI = 'postgresql://YOUR_USER:YOUR_PASSWORD@localhost:5432/YOUR_DB_NAME'

    SUDO_USERS = [254318997]        # full access to the bot
    SUPPORT_USERS = []              # can gban/ungban
    WHITELIST_USERS = []            # can't be banned/kicked by the bot

    LOAD = []                       # empty = load all modules
    NO_LOAD = ['translation', 'rss', 'sed']   # modules you don't want
```

Alternatively, configure with environment variables (set `ENV` to anything to enable this mode — this is what the
`Procfile`/Heroku deployment uses):

| Variable | Description |
| --- | --- |
| `ENV` | Set to anything to enable env-var config |
| `TOKEN` | Bot token from BotFather |
| `OWNER_ID` | Your telegram user ID (integer) |
| `OWNER_USERNAME` | Your telegram username |
| `DATABASE_URL` | Database URI (`postgres://` and `postgresql://` both accepted) |
| `MESSAGE_DUMP` | Optional chat where replied/saved messages are stored |
| `LOAD` | Space-separated modules to load (empty = all) |
| `NO_LOAD` | Space-separated modules to skip |
| `WEBHOOK` | Set to anything to use webhooks instead of long polling |
| `URL` | Public URL for webhooks (webhook mode only) |
| `CERT_PATH` | Path to webhook certificate (optional) |
| `PORT` | Webhook port (default 5000) |
| `SUDO_USERS` | Space-separated user IDs with full bot access |
| `SUPPORT_USERS` | Space-separated user IDs that can gban/ungban |
| `WHITELIST_USERS` | Space-separated user IDs that can't be banned |
| `DONATION_LINK` | Optional donation link shown in `/donate` |
| `DEL_CMDS` | Delete command messages from users without permission |
| `STRICT_GBAN` | Enforce gbans in every group the bot joins |
| `USE_CAS` | Ban new members flagged by the Combot Anti-Spam database |
| `WORKERS` | Worker threads (default 8) |
| `BAN_STICKER` | Sticker sent when someone is banned |
| `ALLOW_EXCL` | Allow `!` as command prefix in addition to `/` |

### 5. Run it

```bash
python3 -m tg_bot
```

You should see `Successfully loaded modules: [...]` followed by `Using long polling.`

Now talk to your bot: `/start` in PM. Then **add it to your groups and promote it as admin** so moderation
commands can work.

### 6. (Optional) Run it as a service

`systemd` unit example:

```ini
[Unit]
Description=tgbot telegram bot
After=network.target postgresql.service

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/tgbot
Environment=ENV=1
EnvironmentFile=/opt/tgbot/.env
ExecStart=/opt/tgbot/.venv/bin/python -m tg_bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

A `Procfile` (`worker: python3 -m tg_bot`) is included for Heroku-style hosts.

---

## Modules

### Load order

`LOAD` and `NO_LOAD` control which modules from `tg_bot/modules/` are loaded. If `LOAD` is empty, all modules load.
`NO_LOAD` takes priority over `LOAD`.

### Creating your own modules

Drop a `.py` file in `tg_bot/modules/`. Register handlers on the `dispatcher` (a PTB v22 `Application`) at import
time. Handlers are `async def` and take `(update, context)`:

```python
from telegram.ext import CommandHandler, filters

from tg_bot import dispatcher


async def hello(update, context):
    await update.effective_message.reply_text("Hello!")


__mod_name__ = "My module"
__help__ = """
 - /hello: says hello
"""

HELLO_HANDLER = CommandHandler("hello", hello, filters=filters.ChatType.GROUPS)
dispatcher.add_handler(HELLO_HANDLER)
```

Module hooks the loader understands:

- `__mod_name__` — friendly module name (used in `/help` and `/settings`)
- `__help__` — help text shown by `/help <module name>`
- `__migrate__(old_chat_id, new_chat_id)` — called when a group is upgraded to a supergroup
- `__stats__()` — stats for the owner's `/stats`
- `__import_data__(chat_id, data)` / `__export_data__(chat_id)` — backups
- `__chat_settings__(chat_id, user_id)` / `__user_settings__(user_id)` — settings menu (may be sync or async)

**Important (PTB v22):** every Telegram API call is a coroutine — always `await` it
(`await message.reply_text(...)`, `await bot.ban_member(...)`). Use `ChatPermissions` for restrictions, and note
that `check_update()` is synchronous: never make API calls there — gate inside the callback instead.

---

## Upgrading from the pre-2026 version

The codebase was migrated from python-telegram-bot 11 (sync) to 22 (async) and SQLAlchemy 1.x to 2.x. Two schema
details changed; fresh databases are created correctly automatically, but if you're reusing an old database:

- `warns.reasons` is now a `JSON` column (was a postgres `ARRAY`). Migrate with
  `ALTER TABLE warns ALTER COLUMN reasons TYPE JSON USING to_json(reasons);` or reset warns.
- Button tables (`note_urls`, `cust_filter_urls`, `welcome_urls`, `leave_urls`) now use `id` as the sole primary
  key. Existing tables keep working on postgres; no action needed.

---

## Documentation & roadmap

Project documentation, architecture notes, and the development roadmap live in the Obsidian vault at
`~/Vault/Projects/tgbot/` — see `AGENTS.md` there for the agent/developer guide and `ROADMAP.md` for what is done
and what is planned.

## Credits

- Original bot: [PaulSonOfLars/tgbot](https://github.com/PaulSonOfLars/tgbot) (Marie)
- Feature inspiration: [Rose](https://t.me/MissRose_bot)
- Everyone who has contributed to this fork.
