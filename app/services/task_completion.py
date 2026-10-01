"""Shared completion and recurrence; caller owns the transaction."""
from ..core.time import current_time
from ..models import Task
from .recurring_tasks import RECURRENCE_NONE, calculate_next_deadline


def complete_task(db, task) -> None:
    now = current_time()
    task.is_completed = True
    task.completed_at = now

    if task.recurrence_type != RECURRENCE_NONE:
        group_id = task.recurrence_group_id or task.id
        task.recurrence_group_id = group_id
        next_deadline = calculate_next_deadline(
            task.deadline,
            task.recurrence_type,
            task.recurrence_interval_days,
        )
        if next_deadline is not None:
            existing_next_task = (
                db.query(Task)
                .filter(
                    Task.user_id == task.user_id,
                    Task.recurrence_group_id == group_id,
                    Task.deadline == next_deadline,
                    Task.is_completed.is_(False),
                )
                .first()
            )
            if existing_next_task is None:
                db.add(
                    Task(
                        user_id=task.user_id,
                        subject_id=task.subject_id,
                        title=task.title,
                        description=task.description,
                        deadline=next_deadline,
                        scheduled_for_date=task.scheduled_for_date,
                        schedule_item_id=task.schedule_item_id,
                        priority=task.priority,
                        difficulty=task.difficulty,
                        is_completed=False,
                        completed_at=None,
                        recurrence_group_id=group_id,
                        recurrence_type=task.recurrence_type,
                        recurrence_interval_days=task.recurrence_interval_days,
                        created_at=now,
                    )
                )

