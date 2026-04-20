from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    group_name = Column(String(50), nullable=True)
    course = Column(Integer, nullable=True)
    schedule_unit = Column(String(20), nullable=False, default='class')
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username = Column(String(100), nullable=True)
    telegram_link_code = Column(String(20), nullable=True)
    telegram_link_code_expires_at = Column(DateTime, nullable=True)
    telegram_linked_at = Column(DateTime, nullable=True)
    telegram_notifications_enabled = Column(Boolean, nullable=False, default=False)
    telegram_deadline_reminders_enabled = Column(Boolean, nullable=False, default=False)
    telegram_schedule_reminders_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    subjects = relationship('Subject', back_populates='user', cascade='all, delete-orphan')
    tasks = relationship('Task', back_populates='user', cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='user', cascade='all, delete-orphan')
    notes = relationship('Note', back_populates='user', cascade='all, delete-orphan')
