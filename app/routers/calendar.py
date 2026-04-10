import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..utils import WEEKDAYS
from .calendar_utils import build_calendar_page_context, build_ics_calendar, normalize_calendar_period
from .common import require_user, templates
from .data_utils import build_download_headers

router = APIRouter()


@router.get('/calendar', response_class=HTMLResponse)
def calendar_page(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    selected: str | None = Query(None),
    view: str = Query('month'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    context = build_calendar_page_context(user, db, year, month, selected, view)
    context.update({'user': user, 'weekdays': WEEKDAYS})
    return templates.TemplateResponse(request, 'calendar.html', context)


@router.get('/calendar/export/ics')
def export_calendar_ics(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    safe_year, safe_month = normalize_calendar_period(year, month)
    calendar_bytes = build_ics_calendar(user, db, safe_year, safe_month)
    filename = f'{user.username}_calendar_{safe_year}-{safe_month:02d}.ics'
    return StreamingResponse(
        io.BytesIO(calendar_bytes),
        media_type='text/calendar; charset=utf-8',
        headers=build_download_headers(filename),
    )
