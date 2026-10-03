import threading

from sqlalchemy import func, distinct, Column, String, UnicodeText

from tg_bot.modules.sql import BASE, SESSION, ENGINE


class BlackListFilters(BASE):
    __tablename__ = "blacklist"
    chat_id = Column(String(50), primary_key=True)
    trigger = Column(UnicodeText, primary_key=True, nullable=False)

    def __init__(self, chat_id, trigger):
        self.chat_id = str(chat_id)  # ensure string
        self.trigger = trigger

    def __repr__(self):
        return "<Blacklist filter '%s' for %s>" % (self.trigger, self.chat_id)

    def __eq__(self, other):
        return bool(isinstance(other, BlackListFilters)
                    and self.chat_id == other.chat_id
                    and self.trigger == other.trigger)


class BlacklistModes(BASE):
    __tablename__ = "blacklist_modes"
    chat_id = Column(String(50), primary_key=True)
    # one of: delete, warn, mute, kick, ban
    mode = Column(UnicodeText, nullable=False, default="delete")

    def __init__(self, chat_id, mode="delete"):
        self.chat_id = str(chat_id)
        self.mode = mode


BlackListFilters.__table__.create(bind=ENGINE, checkfirst=True)
BlacklistModes.__table__.create(bind=ENGINE, checkfirst=True)

BLACKLIST_FILTER_INSERTION_LOCK = threading.RLock()
BLACKLIST_MODE_LOCK = threading.RLock()

CHAT_BLACKLISTS = {}
CHAT_BLACKLIST_MODES = {}

VALID_MODES = ("delete", "warn", "mute", "kick", "ban")


def add_to_blacklist(chat_id, trigger):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        blacklist_filt = BlackListFilters(str(chat_id), trigger)

        SESSION.merge(blacklist_filt)  # merge to avoid duplicate key issues
        SESSION.commit()
        CHAT_BLACKLISTS.setdefault(str(chat_id), set()).add(trigger)


def rm_from_blacklist(chat_id, trigger):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        blacklist_filt = SESSION.query(BlackListFilters).get((str(chat_id), trigger))
        if blacklist_filt:
            if trigger in CHAT_BLACKLISTS.get(str(chat_id), set()):  # sanity check
                CHAT_BLACKLISTS.get(str(chat_id), set()).remove(trigger)

            SESSION.delete(blacklist_filt)
            SESSION.commit()
            return True

        SESSION.close()
        return False


def get_chat_blacklist(chat_id):
    return CHAT_BLACKLISTS.get(str(chat_id), set())


def num_blacklist_filters():
    try:
        return SESSION.query(BlackListFilters).count()
    finally:
        SESSION.close()


def num_blacklist_chat_filters(chat_id):
    try:
        return SESSION.query(BlackListFilters.chat_id).filter(BlackListFilters.chat_id == str(chat_id)).count()
    finally:
        SESSION.close()


def num_blacklist_filter_chats():
    try:
        return SESSION.query(func.count(distinct(BlackListFilters.chat_id))).scalar()
    finally:
        SESSION.close()


def __load_chat_blacklists():
    global CHAT_BLACKLISTS
    try:
        chats = SESSION.query(BlackListFilters.chat_id).distinct().all()
        for (chat_id,) in chats:  # remove tuple by ( ,)
            CHAT_BLACKLISTS[chat_id] = []

        all_filters = SESSION.query(BlackListFilters).all()
        for x in all_filters:
            CHAT_BLACKLISTS[x.chat_id] += [x.trigger]

        CHAT_BLACKLISTS = {x: set(y) for x, y in CHAT_BLACKLISTS.items()}

    finally:
        SESSION.close()


def set_blacklist_mode(chat_id, mode):
    if mode not in VALID_MODES:
        raise ValueError("Invalid blacklist mode: {}".format(mode))
    with BLACKLIST_MODE_LOCK:
        setting = BlacklistModes(str(chat_id), mode)
        SESSION.merge(setting)
        SESSION.commit()
        CHAT_BLACKLIST_MODES[str(chat_id)] = mode


def get_blacklist_mode(chat_id):
    return CHAT_BLACKLIST_MODES.get(str(chat_id), "delete")


def migrate_chat(old_chat_id, new_chat_id):
    with BLACKLIST_FILTER_INSERTION_LOCK:
        chat_filters = SESSION.query(BlackListFilters).filter(BlackListFilters.chat_id == str(old_chat_id)).all()
        for filt in chat_filters:
            filt.chat_id = str(new_chat_id)
        modes = SESSION.query(BlacklistModes).filter(BlacklistModes.chat_id == str(old_chat_id)).all()
        for mode in modes:
            mode.chat_id = str(new_chat_id)
        SESSION.commit()


def __load_chat_blacklist_modes():
    global CHAT_BLACKLIST_MODES
    try:
        for (chat_id, mode) in SESSION.query(BlacklistModes.chat_id, BlacklistModes.mode).all():
            CHAT_BLACKLIST_MODES[chat_id] = mode
    finally:
        SESSION.close()


__load_chat_blacklist_modes()


__load_chat_blacklists()
