# Note: chat_id's are stored as strings because the int is too large to be stored in a PSQL database.
import threading
import time
from collections import namedtuple

from sqlalchemy import Column, Integer, BigInteger, String, Boolean, UnicodeText

from tg_bot.modules.sql import BASE, SESSION, ENGINE

DEF_ENABLED = False
DEF_TYPE = "button"
DEF_TIMEOUT = 120

# In-memory view of one pending challenge, keyed by (chat_id, user_id).
Pending = namedtuple("Pending",
                     ["id", "chat_id", "user_id", "user_name", "message_id", "answer",
                      "captcha_type", "attempts", "expiry"])


class CaptchaSettings(BASE):
    __tablename__ = "captcha_settings"
    chat_id = Column(String(50), primary_key=True)
    enabled = Column(Boolean, default=DEF_ENABLED)
    captcha_type = Column(String(10), default=DEF_TYPE)
    timeout = Column(Integer, default=DEF_TIMEOUT)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string

    def __repr__(self):
        return "<captcha settings for %s>" % self.chat_id


class CaptchaPending(BASE):
    __tablename__ = "captcha_pending"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(50), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(UnicodeText)
    message_id = Column(BigInteger)
    answer = Column(UnicodeText, nullable=False)
    captcha_type = Column(String(10), default=DEF_TYPE)
    attempts = Column(Integer, default=0)
    expiry = Column(BigInteger, default=0)

    def __init__(self, chat_id, user_id, user_name, message_id, answer, captcha_type, expiry):
        self.chat_id = str(chat_id)  # ensure string
        self.user_id = user_id
        self.user_name = user_name
        self.message_id = message_id
        self.answer = answer
        self.captcha_type = captcha_type
        self.expiry = expiry

    def __repr__(self):
        return "<captcha pending for %s in %s>" % (self.user_id, self.chat_id)


CaptchaSettings.__table__.create(bind=ENGINE, checkfirst=True)
CaptchaPending.__table__.create(bind=ENGINE, checkfirst=True)

INSERTION_LOCK = threading.RLock()

CHAT_SETTINGS = {}  # chat_id -> (enabled, captcha_type, timeout)
PENDING = {}  # (chat_id, user_id) -> Pending


def _to_pending(row):
    return Pending(row.id, row.chat_id, row.user_id, row.user_name, row.message_id,
                   row.answer, row.captcha_type, row.attempts, row.expiry)


def get_settings(chat_id):
    return CHAT_SETTINGS.get(str(chat_id), (DEF_ENABLED, DEF_TYPE, DEF_TIMEOUT))


def set_enabled(chat_id, enabled):
    with INSERTION_LOCK:
        settings = SESSION.query(CaptchaSettings).get(str(chat_id))
        if not settings:
            settings = CaptchaSettings(str(chat_id))
        settings.enabled = bool(enabled)
        _, captcha_type, timeout = get_settings(chat_id)
        CHAT_SETTINGS[str(chat_id)] = (bool(enabled), captcha_type, timeout)
        SESSION.add(settings)
        SESSION.commit()


def set_captcha_type(chat_id, captcha_type):
    with INSERTION_LOCK:
        settings = SESSION.query(CaptchaSettings).get(str(chat_id))
        if not settings:
            settings = CaptchaSettings(str(chat_id))
        settings.captcha_type = captcha_type
        enabled, _, timeout = get_settings(chat_id)
        CHAT_SETTINGS[str(chat_id)] = (enabled, captcha_type, timeout)
        SESSION.add(settings)
        SESSION.commit()


def set_timeout(chat_id, timeout):
    with INSERTION_LOCK:
        settings = SESSION.query(CaptchaSettings).get(str(chat_id))
        if not settings:
            settings = CaptchaSettings(str(chat_id))
        settings.timeout = timeout
        enabled, captcha_type, _ = get_settings(chat_id)
        CHAT_SETTINGS[str(chat_id)] = (enabled, captcha_type, timeout)
        SESSION.add(settings)
        SESSION.commit()


def add_pending(chat_id, user_id, user_name, message_id, answer, captcha_type, timeout):
    with INSERTION_LOCK:
        # a rejoin while a challenge is still open replaces the old one
        old = SESSION.query(CaptchaPending).filter(
            CaptchaPending.chat_id == str(chat_id), CaptchaPending.user_id == user_id).all()
        for row in old:
            SESSION.delete(row)

        pending = CaptchaPending(chat_id, user_id, user_name, message_id, answer, captcha_type,
                                 int(time.time()) + timeout)
        SESSION.add(pending)
        SESSION.commit()
        PENDING[(str(chat_id), user_id)] = _to_pending(pending)
        return pending.id


def get_pending(chat_id, user_id):
    return PENDING.get((str(chat_id), user_id))


def set_answer(pending_id, answer):
    with INSERTION_LOCK:
        row = SESSION.query(CaptchaPending).get(pending_id)
        if not row:
            return
        row.answer = answer
        SESSION.commit()
        PENDING[(row.chat_id, row.user_id)] = _to_pending(row)


def bump_attempts(pending_id):
    with INSERTION_LOCK:
        row = SESSION.query(CaptchaPending).get(pending_id)
        if not row:
            return 0
        row.attempts = (row.attempts or 0) + 1
        SESSION.commit()
        PENDING[(row.chat_id, row.user_id)] = _to_pending(row)
        return row.attempts


def rm_pending(chat_id, user_id):
    with INSERTION_LOCK:
        row = SESSION.query(CaptchaPending).filter(
            CaptchaPending.chat_id == str(chat_id), CaptchaPending.user_id == user_id).first()
        if row:
            SESSION.delete(row)
            SESSION.commit()
        PENDING.pop((str(chat_id), user_id), None)


def get_all_pending():
    try:
        return [_to_pending(row) for row in SESSION.query(CaptchaPending).all()]
    finally:
        SESSION.close()


def migrate_chat(old_chat_id, new_chat_id):
    with INSERTION_LOCK:
        settings = SESSION.query(CaptchaSettings).get(str(old_chat_id))
        if settings:
            CHAT_SETTINGS[str(new_chat_id)] = CHAT_SETTINGS.pop(str(old_chat_id),
                                                                (DEF_ENABLED, DEF_TYPE, DEF_TIMEOUT))
            settings.chat_id = str(new_chat_id)

        pendings = SESSION.query(CaptchaPending).filter(
            CaptchaPending.chat_id == str(old_chat_id)).all()
        for row in pendings:
            PENDING.pop((str(old_chat_id), row.user_id), None)
            row.chat_id = str(new_chat_id)
            PENDING[(str(new_chat_id), row.user_id)] = _to_pending(row)

        SESSION.commit()
        SESSION.close()


def __load_captcha_settings():
    global CHAT_SETTINGS, PENDING
    try:
        CHAT_SETTINGS = {settings.chat_id: (bool(settings.enabled), settings.captcha_type,
                                            settings.timeout)
                         for settings in SESSION.query(CaptchaSettings).all()}
        PENDING = {(row.chat_id, row.user_id): _to_pending(row)
                   for row in SESSION.query(CaptchaPending).all()}
    finally:
        SESSION.close()


__load_captcha_settings()
