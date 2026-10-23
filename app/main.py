from threading import BoundedSemaphore

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.decision import ROOT, ServiceError, execute
from app.schemas import LIMITS, DecisionInput

app = FastAPI(title='Microsoft-Decision-1', docs_url=None, redoc_url=None, openapi_url=None)
app.state.slots = BoundedSemaphore(4)


def get_executor():
    return execute


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, error: ServiceError):
    return JSONResponse({'detail': error.message}, status_code=error.status)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    fields = ['.'.join(str(part) for part in item['loc'][1:]) for item in error.errors()]
    return JSONResponse({'detail': '入力内容を確認してください。', 'fields': fields}, status_code=422)


@app.middleware('http')
async def protect_request(request: Request, call_next):
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '別のサイトからの実行は許可されていません。'}, status_code=403)
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return JSONResponse({'detail': 'JSON 形式で送信してください。'}, status_code=415)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin'})
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/decision')
def decide(payload: DecisionInput, request: Request, executor=Depends(get_executor)):
    if not request.app.state.slots.acquire(blocking=False):
        raise ServiceError(429, '現在ほかの処理を実行中です。しばらくしてから再実行してください。')
    try:
        return executor(payload)
    finally:
        request.app.state.slots.release()


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/api/config')
def public_config():
    return {'limits': LIMITS}


@app.get('/')
def index():
    return FileResponse(ROOT / 'app/static/index.html')


app.mount('/static', StaticFiles(directory=ROOT / 'app/static', check_dir=False), name='static')