from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String
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
    display_name = Column(String(40), nullable=True)
    group_name = Column(String(50), nullable=True)
    course = Column(Integer, nullable=True)
    schedule_unit = Column(String(20), nullable=False, default='class')
    last_study_day = Column(Date, nullable=True)
    onboarding_chat_completed = Column(Boolean, nullable=False, default=False)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    onboarding_calendar_opened = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=current_time)

    subjects = relationship('Subject', back_populates='user', cascade='all, delete-orphan')
    tasks = relationship('Task', back_populates='user', cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='user', cascade='all, delete-orphan')
    academic_events = relationship('AcademicEvent', back_populates='user', cascade='all, delete-orphan')
    notes = relationship('Note', back_populates='user', cascade='all, delete-orphan')
