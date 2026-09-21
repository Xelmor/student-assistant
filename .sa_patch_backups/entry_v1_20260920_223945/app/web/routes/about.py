from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..dependencies import templates


router = APIRouter()


@router.get('/about', response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(request, 'about/about.html', {})
