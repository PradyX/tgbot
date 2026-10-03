# Note: chat_id's are stored as strings because the int is too large to be stored in a PSQL database.
import threading

from sqlalchemy import Column, String, Boolean, UnicodeText, Integer, func, distinct

from tg_bot.modules.helper_funcs.msg_types import Types
from tg_bot.modules.sql import BASE, SESSION, ENGINE


class Notes(BASE):
    __tablename__ = "notes"
    chat_id = Column(String(50), primary_key=True)
    name = Column(UnicodeText, primary_key=True)
    value = Column(UnicodeText, nullable=False)
    file = Column(UnicodeText)
    is_reply = Column(Boolean, default=False)
    has_buttons = Column(Boolean, default=False)
    msgtype = Column(Integer, default=Types.BUTTON_TEXT.value)

    def __init__(self, chat_id, name, value, msgtype, file=None):
        self.chat_id = str(chat_id)  # ensure string
        self.name = name
        self.value = value
        self.msgtype = msgtype
        self.file = file

    def __repr__(self):
        return "<Note %s>" % self.name


class NotePrivacy(BASE):
    __tablename__ = "notes_privacy"
    chat_id = Column(String(50), primary_key=True)
    private = Column(Boolean, default=False)

    def __init__(self, chat_id, private):
        self.chat_id = str(chat_id)  # ensure string
        self.private = bool(private)

    def __repr__(self):
        return "<notes privacy for %s>" % self.chat_id


class Buttons(BASE):
    __tablename__ = "note_urls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(50), nullable=False)
    note_name = Column(UnicodeText, nullable=False)
    name = Column(UnicodeText, nullable=False)
    url = Column(UnicodeText, nullable=False)
    same_line = Column(Boolean, default=False)

    def __init__(self, chat_id, note_name, name, url, same_line=False):
        self.chat_id = str(chat_id)
        self.note_name = note_name
        self.name = name
        self.url = url
        self.same_line = same_line


Notes.__table__.create(bind=ENGINE, checkfirst=True)
NotePrivacy.__table__.create(bind=ENGINE, checkfirst=True)
Buttons.__table__.create(bind=ENGINE, checkfirst=True)

NOTES_INSERTION_LOCK = threading.RLock()
BUTTONS_INSERTION_LOCK = threading.RLock()
PRIVACY_INSERTION_LOCK = threading.RLock()

CHAT_PRIVACY = {}  # chat_id -> bool


def add_note_to_db(chat_id, note_name, note_data, msgtype, buttons=None, file=None):
    if not buttons:
        buttons = []

    with NOTES_INSERTION_LOCK:
        prev = SESSION.query(Notes).get((str(chat_id), note_name))
        if prev:
            with BUTTONS_INSERTION_LOCK:
                prev_buttons = SESSION.query(Buttons).filter(Buttons.chat_id == str(chat_id),
                                                             Buttons.note_name == note_name).all()
                for btn in prev_buttons:
                    SESSION.delete(btn)
            SESSION.delete(prev)
        note = Notes(str(chat_id), note_name, note_data or "", msgtype=msgtype.value, file=file)
        SESSION.add(note)
        SESSION.commit()

    for b_name, url, same_line in buttons:
        add_note_button_to_db(chat_id, note_name, b_name, url, same_line)


def get_note(chat_id, note_name):
    try:
        return SESSION.query(Notes).get((str(chat_id), note_name))
    finally:
        SESSION.close()


def rm_note(chat_id, note_name):
    with NOTES_INSERTION_LOCK:
        note = SESSION.query(Notes).get((str(chat_id), note_name))
        if note:
            with BUTTONS_INSERTION_LOCK:
                buttons = SESSION.query(Buttons).filter(Buttons.chat_id == str(chat_id),
                                                        Buttons.note_name == note_name).all()
                for btn in buttons:
                    SESSION.delete(btn)

            SESSION.delete(note)
            SESSION.commit()
            return True

        else:
            SESSION.close()
            return False


def get_all_chat_notes(chat_id):
    try:
        return SESSION.query(Notes).filter(Notes.chat_id == str(chat_id)).order_by(Notes.name.asc()).all()
    finally:
        SESSION.close()


def add_note_button_to_db(chat_id, note_name, b_name, url, same_line):
    with BUTTONS_INSERTION_LOCK:
        button = Buttons(chat_id, note_name, b_name, url, same_line)
        SESSION.add(button)
        SESSION.commit()


def get_buttons(chat_id, note_name):
    try:
        return SESSION.query(Buttons).filter(Buttons.chat_id == str(chat_id), Buttons.note_name == note_name).order_by(
            Buttons.id).all()
    finally:
        SESSION.close()


def get_priv_notes(chat_id):
    return CHAT_PRIVACY.get(str(chat_id), False)


def set_priv_notes(chat_id, private):
    with PRIVACY_INSERTION_LOCK:
        privacy = SESSION.query(NotePrivacy).get(str(chat_id))
        if not privacy:
            privacy = NotePrivacy(str(chat_id), private)
        privacy.private = bool(private)
        CHAT_PRIVACY[str(chat_id)] = bool(private)
        SESSION.add(privacy)
        SESSION.commit()


def num_notes():
    try:
        return SESSION.query(Notes).count()
    finally:
        SESSION.close()


def num_chats():
    try:
        return SESSION.query(func.count(distinct(Notes.chat_id))).scalar()
    finally:
        SESSION.close()


def migrate_chat(old_chat_id, new_chat_id):
    with NOTES_INSERTION_LOCK:
        chat_notes = SESSION.query(Notes).filter(Notes.chat_id == str(old_chat_id)).all()
        for note in chat_notes:
            note.chat_id = str(new_chat_id)

        with BUTTONS_INSERTION_LOCK:
            chat_buttons = SESSION.query(Buttons).filter(Buttons.chat_id == str(old_chat_id)).all()
            for btn in chat_buttons:
                btn.chat_id = str(new_chat_id)

        privacy = SESSION.query(NotePrivacy).get(str(old_chat_id))
        if privacy:
            CHAT_PRIVACY[str(new_chat_id)] = CHAT_PRIVACY.pop(str(old_chat_id), False)
            privacy.chat_id = str(new_chat_id)

        SESSION.commit()


def __load_privacy_settings():
    global CHAT_PRIVACY
    try:
        CHAT_PRIVACY = {row.chat_id: bool(row.private)
                        for row in SESSION.query(NotePrivacy).all()}
    finally:
        SESSION.close()


__load_privacy_settings()
