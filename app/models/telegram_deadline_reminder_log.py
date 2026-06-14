from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..core.database import Base
from ..core.time import current_time


class TelegramDeadlineReminderLog(Base):
    __tablename__ = 'telegram_deadline_reminder_logs'
    __table_args__ = (
        UniqueConstraint(
            'user_id',
            'task_id',
            'reminder_hours',
            'reminder_date_key',
            name='uq_telegram_deadline_reminder_delivery',
        ),
        Index(
            'ix_telegram_deadline_reminder_user_task',
            'user_id',
            'task_id',
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    task_id = Column(
        Integer,
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False,
    )
    reminder_hours = Column(Integer, nullable=False)
    sent_at = Column(DateTime, nullable=False, default=current_time)
    reminder_date_key = Column(String(64), nullable=False)

    user = relationship('User', back_populates='telegram_deadline_reminder_logs')
    task = relationship('Task', back_populates='telegram_deadline_reminder_logs')
