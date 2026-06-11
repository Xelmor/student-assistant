from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


MAX_EXTERNAL_URL_LENGTH = 255
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')


def normalize_bounded_text(
    value: str | None,
    *,
    label: str,
    max_length: int,
    required: bool = False,
) -> str | None:
    normalized = (value or '').strip()
    if not normalized:
        if required:
            raise ValueError(f'Поле «{label}» не должно быть пустым.')
        return None
    if len(normalized) > max_length:
        raise ValueError(f'Поле «{label}» не должно быть длиннее {max_length} символов.')
    if any(
        ord(character) < 32 and character not in {'\n', '\r', '\t'}
        for character in normalized
    ):
        raise ValueError(f'Поле «{label}» содержит недопустимые символы.')
    return normalized


def normalize_choice(value: str | None, *, label: str, allowed: set[str]) -> str:
    normalized = (value or '').strip().lower()
    if normalized not in allowed:
        raise ValueError(f'Поле «{label}» содержит недопустимое значение.')
    return normalized


def normalize_hex_color(value: str | None, *, default: str = '#3b82f6') -> str:
    normalized = (value or default).strip()
    if not HEX_COLOR_PATTERN.fullmatch(normalized):
        raise ValueError('Цвет должен быть указан в формате #RRGGBB.')
    return normalized.lower()


def safe_hex_color(value: str | None, *, default: str = '#3b82f6') -> str:
    try:
        return normalize_hex_color(value, default=default)
    except ValueError:
        return default


def normalize_external_url(value: str | None, *, allow_empty: bool = True) -> str | None:
    normalized = (value or '').strip()
    if not normalized:
        if allow_empty:
            return None
        raise ValueError('Укажи ссылку.')

    if len(normalized) > MAX_EXTERNAL_URL_LENGTH:
        raise ValueError(f'Ссылка не должна быть длиннее {MAX_EXTERNAL_URL_LENGTH} символов.')
    if any(ord(character) < 32 for character in normalized):
        raise ValueError('Ссылка содержит недопустимые символы.')

    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Разрешены только полные ссылки с http:// или https://.')
    if parsed.username or parsed.password:
        raise ValueError('Ссылки со встроенным логином или паролем не поддерживаются.')

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def safe_external_url(value: str | None) -> str | None:
    try:
        return normalize_external_url(value)
    except ValueError:
        return None
