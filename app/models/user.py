from datetime import time

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, String, Time
from sqlalchemy.orm import relationship

from ..core.database import Base
from ..core.time import current_time


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    password_hint = Column(String(120), nullable=True)
    is_local_profile = Column(Boolean, nullable=False, default=False)
    local_access_token_hash = Column(String(64), unique=True, nullable=True, index=True)
    display_name = Column(String(40), nullable=True)
    group_name = Column(String(50), nullable=True)
    course = Column(Integer, nullable=True)
    schedule_unit = Column(String(20), nullable=False, default='class')
    last_study_day = Column(Date, nullable=True)
    onboarding_chat_completed = Column(Boolean, nullable=False, default=False)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    onboarding_calendar_opened = Column(Boolean, nullable=False, default=False)
    telegram_user_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_chat_id = Column(BigInteger, nullable=True)
    telegram_username = Column(String(64), nullable=True)
    telegram_link_code = Column(String(12), unique=True, nullable=True, index=True)
    telegram_link_code_expires_at = Column(DateTime, nullable=True)
    telegram_linked_at = Column(DateTime, nullable=True)
    telegram_morning_digest_enabled = Column(Boolean, nullable=False, default=False)
    telegram_morning_digest_time = Column(
        Time,
        nullable=False,
        default=lambda: time(hour=8),
    )
    telegram_morning_digest_timezone = Column(String(64), nullable=True)
    telegram_morning_digest_last_sent_date = Column(Date, nullable=True)
    telegram_deadline_reminders_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
    )
    telegram_deadline_reminder_hours = Column(Integer, nullable=False, default=24)
    created_at = Column(DateTime, default=current_time)

    subjects = relationship('Subject', back_populates='user', cascade='all, delete-orphan')
    tasks = relationship('Task', back_populates='user', cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='user', cascade='all, delete-orphan')
    academic_events = relationship('AcademicEvent', back_populates='user', cascade='all, delete-orphan')
    notes = relationship('Note', back_populates='user', cascade='all, delete-orphan')
    telegram_deadline_reminder_logs = relationship(
        'TelegramDeadlineReminderLog',
        back_populates='user',
        cascade='all, delete-orphan',
    )
    workspace = relationship(
        'Workspace',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan',
    )
