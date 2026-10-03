from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

from tg_bot import DB_URI

BASE = declarative_base()

# client_encoding is a postgres-only argument; sqlite (used for dev/tests) rejects it.
if DB_URI.startswith("postgresql"):
    ENGINE = create_engine(DB_URI, client_encoding="utf8")
else:
    ENGINE = create_engine(DB_URI)

BASE.metadata.bind = ENGINE
BASE.metadata.create_all(ENGINE)
SESSION = scoped_session(sessionmaker(bind=ENGINE, autoflush=False))

# Telegram user IDs are now 64-bit (they crossed 2^31 in 2025), so every Telegram-ID column is
# BigInteger. `create_all` never alters existing tables, so widen legacy INTEGER columns here:
# without this, a big-ID insert raises NumericValueOutOfRange and poisons the shared session.
if ENGINE.dialect.name == "postgresql":
    _BIGINT_COLUMNS = {
        "users": ["user_id"],
        "chat_members": ["user"],
        "afk_users": ["user_id"],
        "gbans": ["user_id"],
        "user_report_settings": ["user_id"],
        "userinfo": ["user_id"],
        "userbio": ["user_id"],
        "warns": ["user_id"],
        "antiflood": ["user_id"],
        "federations": ["owner_id"],
        "fed_admins": ["user_id"],
        "fed_bans": ["user_id", "banned_by"],
    }
    try:
        # Reflect and alter on a SINGLE connection: doing reflection on a second connection while
        # the ALTER transaction holds locks self-deadlocks (verified against Postgres 16).
        with ENGINE.begin() as _conn:
            _insp = inspect(_conn)
            _existing = set(_insp.get_table_names())
            _types = {
                _table: {c["name"]: c["type"] for c in _insp.get_columns(_table)}
                for _table in _BIGINT_COLUMNS if _table in _existing
            }
            for _table, _cols in _BIGINT_COLUMNS.items():
                for _col in _cols:
                    _type = _types.get(_table, {}).get(_col)
                    if _type is not None and getattr(_type, "__visit_name__", "").lower() == "integer":
                        _conn.execute(text(f'ALTER TABLE "{_table}" ALTER COLUMN "{_col}" TYPE BIGINT'))
    except Exception as _excp:  # never block startup on a best-effort migration
        from tg_bot import LOGGER
        LOGGER.error("Failed to widen legacy INTEGER columns to BIGINT: %s", _excp)
