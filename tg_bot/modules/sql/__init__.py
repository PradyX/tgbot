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

# Telegram IDs are 64-bit (user IDs crossed 2^31 in 2025) and chat IDs are stored as strings, so
# model columns are BigInteger / String(50). `create_all` never alters existing tables, so legacy
# Postgres columns are widened to match the models at startup: INTEGER -> BIGINT and short
# VARCHAR(n) -> the model's length. Without this, an insert like user id 7151438375 or a 15-char
# chat id raises DataError and poisons the shared session (PendingRollbackError everywhere after).
# Driven by BASE.metadata, so new model columns are covered automatically — no list to maintain.
# NOTE: call this only AFTER all modules are imported, or BASE.metadata is still empty.
def widen_legacy_columns():
    if ENGINE.dialect.name != "postgresql":
        return
    try:
        # Reflect and alter on a SINGLE connection: reflecting on a second connection while the
        # ALTER transaction holds locks self-deadlocks (verified against Postgres 16).
        with ENGINE.begin() as _conn:
            _insp = inspect(_conn)
            _existing = set(_insp.get_table_names())
            _db_types = {
                _table.name: {c["name"]: c["type"] for c in _insp.get_columns(_table.name)}
                for _table in BASE.metadata.sorted_tables if _table.name in _existing
            }
            for _table in BASE.metadata.sorted_tables:
                for _col in _table.columns:
                    _db_type = _db_types.get(_table.name, {}).get(_col.name)
                    if _db_type is None:
                        continue
                    _db_visit = getattr(_db_type, "__visit_name__", "").lower()
                    _model_visit = getattr(_col.type, "__visit_name__", "").lower()
                    if _model_visit == "big_integer" and _db_visit == "integer":
                        _conn.execute(text(
                            f'ALTER TABLE "{_table.name}" ALTER COLUMN "{_col.name}" TYPE BIGINT'))
                    elif _model_visit == "string" and _db_visit in ("string", "varchar"):
                        _db_len = getattr(_db_type, "length", None)
                        _model_len = getattr(_col.type, "length", None)
                        if _db_len is not None and _model_len is not None and _db_len < _model_len:
                            _conn.execute(text(
                                f'ALTER TABLE "{_table.name}" ALTER COLUMN "{_col.name}" '
                                f'TYPE VARCHAR({_model_len})'))
    except Exception as _excp:  # never block startup on a best-effort migration
        from tg_bot import LOGGER
        LOGGER.error("Failed to widen legacy columns to match the models: %s", _excp)
