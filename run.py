import os
import uvicorn

if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8000'))
    reload_enabled = os.getenv('RELOAD', 'false').lower() == 'true'
    uvicorn.run('app.main:app', host=host, port=port, reload=reload_enabled)
