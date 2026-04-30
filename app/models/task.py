from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..core.database import Base


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(DateTime, nullable=True)
    scheduled_for_date = Column(Date, nullable=True)
    schedule_item_id = Column(Integer, ForeignKey('schedule_items.id'), nullable=True)
    priority = Column(String(20), default='medium')
    difficulty = Column(String(20), default='medium')
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    recurrence_group_id = Column(Integer, nullable=True, index=True)
    recurrence_type = Column(String(20), nullable=False, default='none')
    recurrence_interval_days = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='tasks')
    subject = relationship('Subject', back_populates='tasks')
    schedule_item = relationship('ScheduleItem', back_populates='tasks')
