from sqlalchemy import Column, ForeignKey, Integer, String, Time
from sqlalchemy.orm import relationship

from ..core.database import Base


class ScheduleItem(Base):
    __tablename__ = 'schedule_items'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=False)
    weekday = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    lesson_type = Column(String(50), nullable=True)
    room = Column(String(50), nullable=True)

    user = relationship('User', back_populates='schedule_items')
    subject = relationship('Subject', back_populates='schedule_items')
