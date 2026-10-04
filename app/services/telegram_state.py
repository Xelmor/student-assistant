from datetime import UTC, datetime, timedelta
from sqlalchemy.exc import IntegrityError
from ..models import TelegramState


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def state_row(db, key):
    row = db.get(TelegramState, key)
    if row is None:
        try:
            with db.begin_nested():
                row = TelegramState(key=key, data={}, expires_at=utcnow())
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.get(TelegramState, key)
    # A real write also serializes SQLite transactions; FOR UPDATE alone does not.
    db.query(TelegramState).filter_by(key=key).update(
        {TelegramState.key: key}, synchronize_session=False,
    )
    db.refresh(row)
    return row


def consume_limit(db, key, limit, seconds):
    row = state_row(db, key)
    now = utcnow()
    count = row.data.get('count', 0) if row.expires_at > now else 0
    if count >= limit:
        return False
    if count == 0:
        row.expires_at = now + timedelta(seconds=seconds)
    row.data = {'count': count + 1}
    db.flush()
    return True
