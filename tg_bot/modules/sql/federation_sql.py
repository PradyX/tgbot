import threading
import uuid

from sqlalchemy import Column, String, UnicodeText, BigInteger, func, distinct

from tg_bot.modules.sql import BASE, SESSION, ENGINE


class Federations(BASE):
    __tablename__ = "federations"
    fed_id = Column(String(36), primary_key=True)
    owner_id = Column(BigInteger, nullable=False)
    fed_name = Column(UnicodeText, nullable=False)

    def __init__(self, owner_id, fed_name):
        self.fed_id = str(uuid.uuid4())
        self.owner_id = owner_id
        self.fed_name = fed_name

    def __repr__(self):
        return "<Federation %s (%s) owned by %s>" % (self.fed_name, self.fed_id, self.owner_id)


class FedChats(BASE):
    __tablename__ = "fed_chats"
    chat_id = Column(String(50), primary_key=True)
    fed_id = Column(String(36), nullable=False)

    def __init__(self, chat_id, fed_id):
        self.chat_id = str(chat_id)
        self.fed_id = fed_id


class FedAdmins(BASE):
    __tablename__ = "fed_admins"
    fed_id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)

    def __init__(self, fed_id, user_id):
        self.fed_id = fed_id
        self.user_id = user_id


class FedBans(BASE):
    __tablename__ = "fed_bans"
    fed_id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    reason = Column(UnicodeText)
    banned_by = Column(BigInteger)

    def __init__(self, fed_id, user_id, reason=None, banned_by=None):
        self.fed_id = fed_id
        self.user_id = user_id
        self.reason = reason
        self.banned_by = banned_by


Federations.__table__.create(bind=ENGINE, checkfirst=True)
FedChats.__table__.create(bind=ENGINE, checkfirst=True)
FedAdmins.__table__.create(bind=ENGINE, checkfirst=True)
FedBans.__table__.create(bind=ENGINE, checkfirst=True)

FED_LOCK = threading.RLock()


def create_fed(owner_id, fed_name):
    with FED_LOCK:
        fed = Federations(owner_id, fed_name)
        SESSION.add(fed)
        SESSION.commit()
        return fed.fed_id, fed.fed_name


def del_fed(fed_id):
    with FED_LOCK:
        fed = SESSION.query(Federations).get(str(fed_id))
        if not fed:
            SESSION.close()
            return False
        SESSION.delete(fed)
        for chat in SESSION.query(FedChats).filter(FedChats.fed_id == str(fed_id)).all():
            SESSION.delete(chat)
        for adm in SESSION.query(FedAdmins).filter(FedAdmins.fed_id == str(fed_id)).all():
            SESSION.delete(adm)
        for ban in SESSION.query(FedBans).filter(FedBans.fed_id == str(fed_id)).all():
            SESSION.delete(ban)
        SESSION.commit()
        return True


def get_fed(fed_id):
    try:
        return SESSION.query(Federations).get(str(fed_id))
    finally:
        SESSION.close()


def get_fed_by_owner(owner_id):
    try:
        return SESSION.query(Federations).filter(Federations.owner_id == owner_id).first()
    finally:
        SESSION.close()


def join_fed(chat_id, fed_id):
    with FED_LOCK:
        existing = SESSION.query(FedChats).get(str(chat_id))
        if existing:
            SESSION.delete(existing)
        SESSION.add(FedChats(chat_id, fed_id))
        SESSION.commit()


def leave_fed(chat_id):
    with FED_LOCK:
        chat = SESSION.query(FedChats).get(str(chat_id))
        if chat:
            SESSION.delete(chat)
            SESSION.commit()
            return True
        SESSION.close()
        return False


def get_chat_fed(chat_id):
    try:
        chat = SESSION.query(FedChats).get(str(chat_id))
        return chat.fed_id if chat else None
    finally:
        SESSION.close()


def get_fed_chats(fed_id):
    try:
        return [chat.chat_id for chat in SESSION.query(FedChats).filter(FedChats.fed_id == str(fed_id)).all()]
    finally:
        SESSION.close()


def set_fed_admin(fed_id, user_id):
    with FED_LOCK:
        SESSION.merge(FedAdmins(str(fed_id), user_id))
        SESSION.commit()


def rm_fed_admin(fed_id, user_id):
    with FED_LOCK:
        adm = SESSION.query(FedAdmins).get((str(fed_id), user_id))
        if adm:
            SESSION.delete(adm)
            SESSION.commit()
            return True
        SESSION.close()
        return False


def get_fed_admins(fed_id):
    try:
        return [adm.user_id for adm in SESSION.query(FedAdmins).filter(FedAdmins.fed_id == str(fed_id)).all()]
    finally:
        SESSION.close()


def is_fed_admin(fed_id, user_id):
    fed = get_fed(fed_id)
    if not fed:
        return False
    return fed.owner_id == user_id or user_id in get_fed_admins(fed_id)


def fban_user(fed_id, user_id, reason=None, banned_by=None):
    with FED_LOCK:
        SESSION.merge(FedBans(str(fed_id), user_id, reason=reason, banned_by=banned_by))
        SESSION.commit()


def unfban_user(fed_id, user_id):
    with FED_LOCK:
        ban = SESSION.query(FedBans).get((str(fed_id), user_id))
        if ban:
            SESSION.delete(ban)
            SESSION.commit()
            return True
        SESSION.close()
        return False


def get_fban(fed_id, user_id):
    try:
        return SESSION.query(FedBans).get((str(fed_id), user_id))
    finally:
        SESSION.close()


def get_fban_list(fed_id):
    try:
        return SESSION.query(FedBans).filter(FedBans.fed_id == str(fed_id)).all()
    finally:
        SESSION.close()


def num_feds():
    try:
        return SESSION.query(Federations).count()
    finally:
        SESSION.close()


def num_fed_chats():
    try:
        return SESSION.query(func.count(distinct(FedChats.chat_id))).scalar() or 0
    finally:
        SESSION.close()


def num_fed_bans():
    try:
        return SESSION.query(FedBans).count()
    finally:
        SESSION.close()


def migrate_chat(old_chat_id, new_chat_id):
    with FED_LOCK:
        chat = SESSION.query(FedChats).get(str(old_chat_id))
        if chat:
            chat.chat_id = str(new_chat_id)
            SESSION.commit()
