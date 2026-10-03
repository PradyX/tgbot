# AGENTS.md — tgbot

Modular Telegram group-management bot (Marie fork, Rose-style features).
**Python 3.10+ · python-telegram-bot 22 (async) · SQLAlchemy 2.x · PostgreSQL (prod) / SQLite (dev).**

Full documentation lives in the Obsidian vault at `~/Vault/Projects/tgbot/` (AGENTS.md, ROADMAP, docs/).
This file is the in-repo quick reference.

## Run & verify

```bash
source .venv/bin/activate        # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python -m compileall -q tg_bot

# smoke test (fake token; "Successfully loaded modules" then InvalidToken = success)
rm -f /tmp/ptb_test.db
ENV=1 TOKEN="123456:TESTTOKEN" OWNER_ID=1 OWNER_USERNAME=test SUDO_USERS="1" \
  DATABASE_URL="sqlite:////tmp/ptb_test.db" NO_LOAD="translation rss sed" python -m tg_bot
```

## Architecture in 30 seconds

- `tg_bot/__init__.py` loads config (env vars if `ENV` set, else `tg_bot/config.py` extending
  `sample_config.Config`) and builds `application`, aliased as `dispatcher`.
- `tg_bot/__main__.py` imports every `tg_bot/modules/*.py`; each module registers handlers at import time via
  `dispatcher.add_handler(...)` and exposes optional hooks (`__mod_name__`, `__help__`, `__migrate__`,
  `__stats__`, `__chat_settings__`, `__user_settings__`, `__import_data__`, `__export_data__`).
- `tg_bot/modules/sql/*_sql.py` hold SQLAlchemy models + data access (`BASE`, `SESSION`, `ENGINE`).
- `tg_bot/modules/helper_funcs/` holds permission decorators (`chat_status`), extraction/parsing helpers.

## Hard rules (PTB 22)

1. **Everything Telegram is async** — `await` every API call; helpers that call the API must be `async` and
   awaited by their callers. Missed awaits fail silently.
2. **`check_update()` is sync** — never call the API there; gate inside the callback (see `DisableAbleCommandHandler`
   in `modules/disable.py`).
3. **No `bot.id` / `bot.username` / `bot.first_name` at import time** — they raise before initialization; format
   lazily inside handlers.
4. Handlers are `async def handler(update, context)`; `context.args` replaces `pass_args`.
5. Filters take the **Update** (`filters.Regex(...)(update)`); v22 filter names differ (`filters.ChatType.GROUPS`,
   `filters.StatusUpdate.MIGRATE`, `filters.Sticker.ALL`, ...).
6. Restrictions use `ChatPermissions` (`restrict_chat_member(..., permissions=..., until_date=...)`); kick is
   `ban_member` + `unban_member`.
7. Parse modes: `mention_html`/HTML tags → `ParseMode.HTML`; `_italic_`/`*bold*` → `ParseMode.MARKDOWN`.
8. SQL: portable column types only (no postgres `ARRAY`); `.__table__.create(bind=ENGINE, checkfirst=True)`;
   follow the in-memory-cache pattern of existing `*_sql.py` files.
9. Decorator order on handlers: `@bot_admin`/`@user_admin`/... outermost, `@loggable` innermost; `@loggable`
   handlers return an HTML log string (or `""`).
10. Keep the update rate limiter (`TypeHandler` at group -100 in `__main__.py`) working.

## Conventions

- Module = one file in `tg_bot/modules/`; user-facing toggleable commands use `DisableAbleCommandHandler`.
- Log strings: `"<b>{chat}:</b>\n#TAG\n<b>Admin:</b> ...\n<b>User:</b> ..."`.
- Catch `BadRequest` narrowly via `excp.message`; re-raise unexpected errors.
- Time values parse via `extract_time` (`m`/`h`/`d`); users via `extract_user`/`extract_user_and_text` (async).

## Docs map

Repo `README.md` (setup guide) · vault `~/Vault/Projects/tgbot/` → [[AGENTS]], [[ROADMAP]], [[Modules]],
[[Architecture]], [[Database Schema]], [[Development Guide]], [[Upgrade Notes]], [[CHANGELOG]].
