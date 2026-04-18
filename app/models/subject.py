from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..core.database import Base


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
