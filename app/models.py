from datetime import datetime, time
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Date, Time
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    group_name = Column(String(50), nullable=True)
    course = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    subjects = relationship('Subject', back_populates='user', cascade='all, delete-orphan')
    tasks = relationship('Task', back_populates='user', cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='user', cascade='all, delete-orphan')
    notes = relationship('Note', back_populates='user', cascade='all, delete-orphan')
    telegram_binding = relationship('TelegramBinding', back_populates='user', uselist=False, cascade='all, delete-orphan')
    telegram_link_codes = relationship('TelegramLinkCode', back_populates='user', cascade='all, delete-orphan')


class Subject(Base):
    __tablename__ = 'subjects'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(100), nullable=False)
    teacher = Column(String(100), nullable=True)
    room = Column(String(50), nullable=True)
    color = Column(String(20), default='#0d6efd')
    notes = Column(Text, nullable=True)

    user = relationship('User', back_populates='subjects')
    tasks = relationship('Task', back_populates='subject', cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='subject', cascade='all, delete-orphan')
    note_items = relationship('Note', back_populates='subject', cascade='all, delete-orphan')


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(DateTime, nullable=True)
    priority = Column(String(20), default='medium')
    difficulty = Column(String(20), default='medium')
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='tasks')
    subject = relationship('Subject', back_populates='tasks')


class ScheduleItem(Base):
    __tablename__ = 'schedule_items'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=False)
    weekday = Column(Integer, nullable=False)  # 0=Mon ... 6=Sun
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    lesson_type = Column(String(50), nullable=True)
    room = Column(String(50), nullable=True)

    user = relationship('User', back_populates='schedule_items')
    subject = relationship('Subject', back_populates='schedule_items')


class Note(Base):
    __tablename__ = 'notes'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=True)
    title = Column(String(150), nullable=False)
    content = Column(Text, nullable=True)
    link = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='notes')
    subject = relationship('Subject', back_populates='note_items')


class TelegramBinding(Base):
    __tablename__ = 'telegram_bindings'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True, index=True)
    telegram_user_id = Column(String(32), nullable=False, unique=True, index=True)
    telegram_username = Column(String(64), nullable=True)
    linked_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship('User', back_populates='telegram_binding')


class TelegramLinkCode(Base):
    __tablename__ = 'telegram_link_codes'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    code = Column(String(20), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship('User', back_populates='telegram_link_codes')
