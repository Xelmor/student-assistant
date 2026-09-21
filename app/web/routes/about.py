from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.security import get_current_user
from ..dependencies import templates


router = APIRouter()


@router.get('/about', response_class=HTMLResponse)
def about_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(request, 'about/about.html', {'user': user})
