from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AIAssistantEntry
from ..settings import settings
from ..services.ai_service import (
    FEATURE_ASSISTANT_CHAT,
    AIConfigurationError,
    AIServiceError,
    ai_service,
)
from .common import require_user, templates, validate_csrf

router = APIRouter()

SUGGESTED_PROMPTS = [
    'Сделай план подготовки к экзамену по математическому анализу за 10 дней, если я могу заниматься по 2 часа в день.',
    'Разбей задачу: написать курсовую по истории до следующей пятницы, если свободен по вечерам.',
    'Оцени, сколько времени нужно, чтобы подготовиться к коллоквиуму по физике на хорошую оценку.',
]


def validate_prompt(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError('Введите запрос для AI Assistant.')
    if len(normalized) > settings.ai_input_max_length:
        raise ValueError(
            f'Запрос слишком длинный. Максимум {settings.ai_input_max_length} символов.'
        )
    return normalized


def upsert_ai_entry(
    db: Session,
    *,
    user_id: int,
    feature_type: str,
    input_summary: str,
    result_text: str,
):
    entry = (
        db.query(AIAssistantEntry)
        .filter(AIAssistantEntry.user_id == user_id, AIAssistantEntry.feature_type == feature_type)
        .first()
    )
    if not entry:
        entry = AIAssistantEntry(
            user_id=user_id,
            feature_type=feature_type,
            input_summary=input_summary,
            result_text=result_text,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
    else:
        entry.input_summary = input_summary
        entry.result_text = result_text
        entry.created_at = datetime.utcnow()

    db.commit()


def get_entry(db: Session, *, user_id: int, feature_type: str):
    return (
        db.query(AIAssistantEntry)
        .filter(AIAssistantEntry.user_id == user_id, AIAssistantEntry.feature_type == feature_type)
        .first()
    )


def render_ai_page(
    request: Request,
    *,
    user,
    db: Session,
    prompt_text: str = '',
    current_result: dict | None = None,
    current_error: str | None = None,
):
    return templates.TemplateResponse(
        request,
        'ai_assistant.html',
        {
            'user': user,
            'prompt_text': prompt_text,
            'current_result': current_result,
            'current_error': current_error,
            'latest_entry': get_entry(db, user_id=user.id, feature_type=FEATURE_ASSISTANT_CHAT),
            'ai_configured': ai_service.is_configured(),
            'ai_input_max_length': settings.ai_input_max_length,
            'suggested_prompts': SUGGESTED_PROMPTS,
        },
    )


@router.get('/ai/assistant', response_class=HTMLResponse)
def ai_assistant_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    return render_ai_page(request, user=user, db=db)


@router.post('/ai/assistant', response_class=HTMLResponse)
def generate_ai_response(
    request: Request,
    prompt_text: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    try:
        normalized_prompt = validate_prompt(prompt_text)
        result = ai_service.answer_study_request(request_text=normalized_prompt)
        upsert_ai_entry(
            db,
            user_id=user.id,
            feature_type=FEATURE_ASSISTANT_CHAT,
            input_summary=normalized_prompt[:180],
            result_text=result.text,
        )
        return render_ai_page(
            request,
            user=user,
            db=db,
            prompt_text=normalized_prompt,
            current_result={'title': result.title, 'text': result.text},
        )
    except ValueError as exc:
        return render_ai_page(
            request,
            user=user,
            db=db,
            prompt_text=prompt_text,
            current_error=str(exc),
        )
    except (AIConfigurationError, AIServiceError) as exc:
        return render_ai_page(
            request,
            user=user,
            db=db,
            prompt_text=prompt_text,
            current_error=exc.user_message,
        )
    except Exception:
        db.rollback()
        return render_ai_page(
            request,
            user=user,
            db=db,
            prompt_text=prompt_text,
            current_error='Во время обработки запроса произошла ошибка. Проверьте настройки OpenAI и попробуйте снова.',
        )
