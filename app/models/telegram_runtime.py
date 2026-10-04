"""Durable Telegram state. Times in these tables are naive UTC."""
from sqlalchemy import BigInteger, Column, DateTime, Integer, JSON, String
from ..core.database import Base


class TelegramUpdate(Base):
    __tablename__ = 'telegram_updates'
    update_id = Column(BigInteger, primary_key=True, autoincrement=False)
    reply = Column(JSON, nullable=True)
    user_id = Column(Integer, nullable=True)
    telegram_user_id = Column(BigInteger, nullable=True)
    status = Column(String(20), nullable=False, default='pending')
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False)
    error_category = Column(String(40), nullable=True)


class TelegramState(Base):
    __tablename__ = 'telegram_state'
    key = Column(String(100), primary_key=True)
    data = Column(JSON, nullable=False, default=dict)
    expires_at = Column(DateTime, nullable=False)
