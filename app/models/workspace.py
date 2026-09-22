from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base
from ..core.time import current_time


class Workspace(Base):
    __tablename__ = 'workspaces'

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    display_name = Column(String(80), nullable=False)
    recovery_key_hash = Column(String(64), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=current_time)
    updated_at = Column(DateTime, nullable=False, default=current_time, onupdate=current_time)

    user = relationship('User', back_populates='workspace')
    devices = relationship(
        'WorkspaceDevice',
        back_populates='workspace',
        cascade='all, delete-orphan',
    )
    link_sessions = relationship(
        'DeviceLinkSession',
        back_populates='workspace',
        cascade='all, delete-orphan',
    )


class WorkspaceDevice(Base):
    __tablename__ = 'workspace_devices'

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer,
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    device_id = Column(String(36), unique=True, nullable=False, index=True)
    device_name = Column(String(80), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=current_time)
    last_seen_at = Column(DateTime, nullable=False, default=current_time)
    revoked_at = Column(DateTime, nullable=True)
    user_agent = Column(String(255), nullable=True)

    workspace = relationship('Workspace', back_populates='devices')
    created_link_sessions = relationship(
        'DeviceLinkSession',
        back_populates='created_by_device',
        foreign_keys='DeviceLinkSession.created_by_device_id',
    )


class DeviceLinkSession(Base):
    __tablename__ = 'device_link_sessions'

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer,
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=current_time)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_by_device_id = Column(
        Integer,
        ForeignKey('workspace_devices.id', ondelete='SET NULL'),
        nullable=True,
    )

    workspace = relationship('Workspace', back_populates='link_sessions')
    created_by_device = relationship(
        'WorkspaceDevice',
        back_populates='created_link_sessions',
        foreign_keys=[created_by_device_id],
    )
