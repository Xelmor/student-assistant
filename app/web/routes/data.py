import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.data_service import (
    build_csv_export_archive,
    build_download_headers,
    build_user_export_payload,
    import_user_export_payload,
)
from ..dependencies import profile_message_redirect, require_user, validate_csrf

router = APIRouter()


@router.get('/data/export/{export_format}')
@router.get('/data/export/{export_format}/')
def export_data(export_format: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    payload = build_user_export_payload(user, db)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
    safe_username = ''.join(character for character in user.username if character.isalnum() or character in {'-', '_'}) or 'student'

    if export_format == 'json':
        json_buffer = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
        filename = f'{safe_username}_student_assistant_backup_{timestamp}.json'
        return StreamingResponse(
            json_buffer,
            media_type='application/octet-stream',
            headers=build_download_headers(filename),
        )

    if export_format == 'csv':
        archive_buffer = build_csv_export_archive(payload)
        filename = f'{safe_username}_student_assistant_export_{timestamp}.zip'
        return StreamingResponse(
            archive_buffer,
            media_type='application/zip',
            headers=build_download_headers(filename),
        )

    return profile_message_redirect(error='Неподдерживаемый формат экспорта.')


@router.post('/data/import')
async def import_data(
    request: Request,
    import_file: UploadFile = File(...),
    import_mode: str = Form('merge'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if import_mode not in {'merge', 'replace'}:
        return profile_message_redirect(error='Неизвестный режим импорта.')

    if not import_file.filename:
        return profile_message_redirect(error='Выбери JSON-файл для импорта.')

    if not import_file.filename.lower().endswith('.json'):
        return profile_message_redirect(error='Сейчас импорт поддерживается только из JSON-файла.')

    file_bytes = await import_file.read()
    if not file_bytes:
        return profile_message_redirect(error='Файл пустой.')

    try:
        payload = json.loads(file_bytes.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return profile_message_redirect(error='Не удалось прочитать JSON-файл. Проверь формат.')

    try:
        import_user_export_payload(user, payload, import_mode, db)
        db.commit()
    except ValueError as error:
        db.rollback()
        return profile_message_redirect(error=str(error))
    except Exception:
        db.rollback()
        return profile_message_redirect(error='Импорт не удался из-за ошибки в данных.')

    return profile_message_redirect(success='Данные успешно импортированы.')
