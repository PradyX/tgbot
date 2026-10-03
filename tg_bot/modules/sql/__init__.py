from sqlalchemy import create_engine
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
