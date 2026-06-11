from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import relationship

from ..core.database import Base
from ..core.time import current_time


class AcademicEvent(Base):
    __tablename__ = 'academic_events'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=True)
    title = Column(String(150), nullable=False)
    event_type = Column(String(20), nullable=False, default='exam')
    event_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    room = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=current_time)

    user = relationship('User', back_populates='academic_events')
    subject = relationship('Subject')
