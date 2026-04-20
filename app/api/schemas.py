from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubjectResponse(BaseModel):
    id: int
    name: str
    teacher: str | None
    room: str | None
    color: str
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class NoteResponse(BaseModel):
    id: int
    title: str
    content: str | None
    link: str | None
    subject_name: str | None = None
    created_at: datetime | None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    deadline: datetime | None
    priority: str
    difficulty: str
    is_completed: bool
    subject_id: int | None
    subject_name: str | None = None
    created_at: datetime | None


class ScheduleItemResponse(BaseModel):
    id: int
    weekday: int
    weekday_name: str
    start_time: str
    end_time: str
    lesson_type: str | None
    room: str | None
    subject_id: int
    subject_name: str


class ReminderSettingsResponse(BaseModel):
    notifications_enabled: bool
    deadline_reminders_enabled: bool
    schedule_reminders_enabled: bool


class ReminderSettingsUpdate(BaseModel):
    notifications_enabled: bool | None = None
    deadline_reminders_enabled: bool | None = None
    schedule_reminders_enabled: bool | None = None


class TelegramLinkCodeResponse(BaseModel):
    code: str
    expires_at: datetime | None
    linked_chat_id: int | None
    linked_username: str | None


class TelegramLinkConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    chat_id: int
    telegram_username: str | None = None


class TelegramLinkConfirmResponse(BaseModel):
    success: bool
    username: str


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=4000)
    subject_id: int | None = None
    deadline: datetime | None = None
    priority: str = 'medium'
    difficulty: str = 'medium'
