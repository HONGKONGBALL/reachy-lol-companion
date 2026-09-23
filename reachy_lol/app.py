from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import os
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field
from .runtime import Runtime
from .settings import Preferences
from .identity import OwnerReport

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
PORT=int(os.getenv('REACHY_LOL_PORT','8768'))
if not 1024<=PORT<=65535:
    raise ValueError('REACHY_LOL_PORT must be between 1024 and 65535')
runtime = Runtime(ROOT)
TOKEN = secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app):
    await runtime.boot()
    yield
    await runtime.shutdown()


app = FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host','')
    if host not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}','testserver'):
        return JSONResponse({'error':'Localhost only'},status_code=403)
    origin = request.headers.get('origin')
    if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
        return JSONResponse({'error':'Invalid origin'},status_code=403)
    if request.url.path.startswith('/api/') and request.headers.get('x-demo-token')!=TOKEN:
        return JSONResponse({'error':'Invalid local token'},status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@app.get('/',response_class=HTMLResponse)
async def index():
    return (ROOT/'reachy_lol'/'index.html').read_text(encoding='utf8').replace('__TOKEN__',TOKEN)

@app.get('/app.js')
async def javascript():
    return FileResponse(ROOT/'reachy_lol'/'app.js',media_type='application/javascript')

@app.get('/diagnostics',response_class=HTMLResponse)
async def diagnostics_page():
    return (ROOT/'reachy_lol'/'diagnostics.html').read_text(encoding='utf8').replace('__TOKEN__',TOKEN)

@app.get('/api/preferences')
async def preferences():
    return runtime.preferences_snapshot()

@app.put('/api/preferences')
async def save_preferences(payload:Preferences):
    try:
        return await runtime.save_preferences(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


class SeatSetting(BaseModel):
    yaw: float=Field(ge=-20,le=20,allow_inf_nan=False)


@app.post('/api/seat')
async def seat_setting(payload:SeatSetting):
    try:
        return await runtime.configure_seat(payload.yaw)
    except (ValueError,RuntimeError) as exc:
        raise HTTPException(400,str(exc))


@app.post('/api/data/clear')
async def clear_local_data():
    try:
        return await runtime.clear_local_data()
    except (ValueError,OSError) as exc:
        raise HTTPException(400,str(exc))

@app.post('/api/audition/{profile}')
async def audition(profile:str):
    try:
        return await runtime.audition(profile)
    except (ValueError,RuntimeError) as exc:
        raise HTTPException(400,str(exc))


@app.get('/api/state')
async def state():
    return runtime.snapshot()


class FriendConfirmation(BaseModel):
    name: str = Field(min_length=1,max_length=160)
    nickname: str = Field(default='',max_length=40)


class IdentityConfirmation(BaseModel):
    match_id: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=160)
    friends: list[FriendConfirmation] = Field(default_factory=list,max_length=4)


@app.put('/api/identity/report')
async def report_identity(payload:OwnerReport):
    try:
        return await runtime.report_identity(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@app.post('/api/identity/refresh')
async def refresh_identity():
    try:
        return await runtime.probe_identity()
    except Exception as exc:
        runtime.identities.disconnect()
        runtime.identity=None
        raise HTTPException(400,'暂时无法读取本局身份：'+type(exc).__name__)


@app.put('/api/identity')
async def confirm_identity(payload:IdentityConfirmation):
    try:
        return await runtime.confirm_identity(payload.match_id,payload.name,
                                              [f.model_dump() for f in payload.friends])
    except ValueError as exc:
        raise HTTPException(400,str(exc))


class Control(BaseModel):
    action: str
    value: str | float | int | None = None


@app.post('/api/control')
async def control(payload:Control):
    try:
        await runtime.control(payload.action,payload.value)
        return {'ok':True}
    except (ValueError,RuntimeError) as exc:
        raise HTTPException(400,str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(400,'连接官方机器人后台失败：'+type(exc).__name__)


@app.post('/api/diagnostic/{kind}')
async def diagnostic(kind:str):
    try:
        return await runtime.diagnostic(kind)
    except Exception as exc:
        raise HTTPException(400,f'{type(exc).__name__}: {exc}')


class TextInput(BaseModel):
    text: str = Field(min_length=1,max_length=500)


@app.post('/api/text')
async def text_input(payload:TextInput):
    if not runtime.gate.running or runtime.gate.paused:
        raise HTTPException(400,'先开始陪玩并恢复采集')
    await runtime.owner_text(payload.text)
    return {'ok':True,'evidence_type':'manual_text_diagnostic'}


@app.post('/api/reload-config')
async def reload_config():
    if runtime.gate.running:
        raise HTTPException(400,'请结束会话后更新配置')
    load_dotenv(ROOT/'.env',override=True)
    return {'configured':{k:runtime.cloud.configured(k) for k in ('vision','chat','asr','tts')}}
