from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.time import current_time
from ..models import DeviceLinkSession, User, Workspace, WorkspaceDevice


LINK_TTL_MINUTES = 5
MAX_LINK_ATTEMPTS = 8
RECOVERY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _secret_hash(value: str, purpose: str) -> str:
    payload = f'{purpose}:{value}'.encode('utf-8')
    return hmac.new(settings.secret_key.encode('utf-8'), payload, hashlib.sha256).hexdigest()


def hash_device_token(token: str) -> str:
    return _secret_hash(token.strip(), 'workspace-device')


def normalize_pairing_code(code: str) -> str:
    return ''.join(character for character in code if character.isdigit())


def hash_pairing_code(code: str) -> str:
    return _secret_hash(normalize_pairing_code(code), 'workspace-link-code')


def hash_link_token(token: str) -> str:
    return _secret_hash(token.strip(), 'workspace-link-token')


def normalize_recovery_key(key: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', key.upper())


def hash_recovery_key(key: str) -> str:
    return _secret_hash(normalize_recovery_key(key), 'workspace-recovery')


def generate_recovery_key() -> str:
    body = ''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(20))
    return 'SA-' + '-'.join(body[index:index + 4] for index in range(0, len(body), 4))


def infer_device_name(user_agent: str | None) -> str:
    value = (user_agent or '').lower()
    if 'iphone' in value:
        return 'iPhone'
    if 'ipad' in value:
        return 'iPad'
    if 'android' in value:
        return 'Android-устройство'
    if 'macintosh' in value or 'mac os' in value:
        return 'Mac'
    if 'windows' in value:
        return 'Windows PC'
    if 'linux' in value:
        return 'Linux PC'
    return 'Новое устройство'


def create_workspace(
    db: Session,
    user: User,
    *,
    display_name: str | None = None,
    with_recovery_key: bool = True,
) -> tuple[Workspace, str | None]:
    recovery_key = generate_recovery_key() if with_recovery_key else None
    workspace = Workspace(
        public_id=str(uuid4()),
        user=user,
        display_name=(display_name or user.display_name or user.username)[:80],
        recovery_key_hash=hash_recovery_key(recovery_key) if recovery_key else None,
        is_active=True,
    )
    db.add(workspace)
    db.flush()
    return workspace, recovery_key


def ensure_workspace(db: Session, user: User) -> Workspace:
    workspace = db.query(Workspace).filter(Workspace.user_id == user.id).first()
    if workspace:
        return workspace
    workspace, _ = create_workspace(db, user, with_recovery_key=False)
    return workspace


def create_device(
    db: Session,
    workspace: Workspace,
    *,
    device_name: str,
    user_agent: str | None,
    token_hash: str | None = None,
    raw_token: str | None = None,
) -> tuple[WorkspaceDevice, str | None]:
    if token_hash and raw_token:
        raise ValueError('Provide either token_hash or raw_token, not both.')
    issued_token = None if token_hash else (raw_token or secrets.token_urlsafe(48))
    device = WorkspaceDevice(
        workspace=workspace,
        device_id=str(uuid4()),
        device_name=(device_name.strip() or infer_device_name(user_agent))[:80],
        token_hash=token_hash or hash_device_token(issued_token or ''),
        user_agent=(user_agent or '')[:255] or None,
        created_at=current_time(),
        last_seen_at=current_time(),
    )
    db.add(device)
    workspace.updated_at = current_time()
    db.flush()
    return device, issued_token


def issue_link_session(
    db: Session,
    workspace: Workspace,
    *,
    created_by_device: WorkspaceDevice,
) -> tuple[DeviceLinkSession, str, str]:
    now = current_time()
    db.query(DeviceLinkSession).filter(
        DeviceLinkSession.workspace_id == workspace.id,
        DeviceLinkSession.used_at.is_(None),
    ).update({'used_at': now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    for _ in range(20):
        code = f'{secrets.randbelow(1_000_000):06d}'
        if not db.query(DeviceLinkSession).filter(
            DeviceLinkSession.code_hash == hash_pairing_code(code)
        ).first():
            break
    else:
        raise RuntimeError('Не удалось безопасно создать код подключения.')

    link_session = DeviceLinkSession(
        workspace=workspace,
        code_hash=hash_pairing_code(code),
        token_hash=hash_link_token(raw_token),
        created_at=now,
        expires_at=now + timedelta(minutes=LINK_TTL_MINUTES),
        created_by_device=created_by_device,
    )
    db.add(link_session)
    db.flush()
    return link_session, code, raw_token


def get_active_link_session(
    db: Session,
    *,
    code: str | None = None,
    token: str | None = None,
    lock: bool = False,
) -> DeviceLinkSession | None:
    if bool(code) == bool(token):
        return None
    query = db.query(DeviceLinkSession)
    if lock:
        query = query.with_for_update()
    if code:
        normalized_code = normalize_pairing_code(code)
        if len(normalized_code) != 6:
            return None
        query = query.filter(DeviceLinkSession.code_hash == hash_pairing_code(normalized_code))
    else:
        query = query.filter(DeviceLinkSession.token_hash == hash_link_token(token or ''))
    link_session = query.first()
    if not link_session:
        return None
    if (
        link_session.used_at is not None
        or link_session.expires_at <= current_time()
        or link_session.attempt_count >= MAX_LINK_ATTEMPTS
        or not link_session.workspace.is_active
    ):
        return None
    return link_session


def consume_link_session(
    db: Session,
    *,
    device_name: str,
    user_agent: str | None,
    code: str | None = None,
    token: str | None = None,
) -> tuple[User, WorkspaceDevice, str] | None:
    link_session = get_active_link_session(db, code=code, token=token, lock=True)
    if not link_session:
        return None
    now = current_time()
    claimed = db.query(DeviceLinkSession).filter(
        DeviceLinkSession.id == link_session.id,
        DeviceLinkSession.used_at.is_(None),
        DeviceLinkSession.expires_at > now,
        DeviceLinkSession.attempt_count < MAX_LINK_ATTEMPTS,
    ).update(
        {
            DeviceLinkSession.used_at: now,
            DeviceLinkSession.attempt_count: DeviceLinkSession.attempt_count + 1,
        },
        synchronize_session=False,
    )
    if claimed != 1:
        return None
    device, raw_device_token = create_device(
        db,
        link_session.workspace,
        device_name=device_name,
        user_agent=user_agent,
    )
    db.flush()
    return link_session.workspace.user, device, raw_device_token or ''


def recover_workspace(
    db: Session,
    *,
    recovery_key: str,
    device_name: str,
    user_agent: str | None,
) -> tuple[User, WorkspaceDevice, str] | None:
    normalized = normalize_recovery_key(recovery_key)
    if len(normalized) != 22 or not normalized.startswith('SA'):
        return None
    workspace = db.query(Workspace).filter(
        Workspace.recovery_key_hash == hash_recovery_key(normalized),
        Workspace.is_active.is_(True),
    ).with_for_update().first()
    if not workspace:
        return None
    device, raw_token = create_device(
        db,
        workspace,
        device_name=device_name,
        user_agent=user_agent,
    )
    return workspace.user, device, raw_token or ''


def rotate_recovery_key(workspace: Workspace) -> str:
    recovery_key = generate_recovery_key()
    workspace.recovery_key_hash = hash_recovery_key(recovery_key)
    workspace.updated_at = current_time()
    return recovery_key


def qr_svg_data_uri(value: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as error:  # pragma: no cover - dependency validated at deployment
        raise RuntimeError('QR dependency is not installed.') from error

    image = qrcode.make(
        value,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=7,
        border=2,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'
