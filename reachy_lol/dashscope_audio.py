"""Cancellable CosyVoice WebSocket transport; return PCM16 WAV for the player."""
import asyncio
import io
import json
import re
import time
import uuid
import wave
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from .usage import record


async def synthesize(config, text, voice, usage):
    if not config.configured:
        raise RuntimeError('请配置完整的 TTS_BASE_URL / TTS_API_KEY / TTS_MODEL')
    url = urlsplit(config.base_url)
    if url.path.rstrip('/') != '/api/v1':
        raise RuntimeError('百炼 TTS_BASE_URL 须使用 HTTPS 地址并以 /api/v1 结尾')
    endpoint = urlunsplit(('wss', url.netloc, '/api-ws/v1/inference', '', ''))
    task_id = uuid.uuid4().hex
    started = time.monotonic()
    status, units, first_ms = 'failed', {}, None
    pcm = bytearray()
    rate = 24000

    def packet(action, payload):
        return json.dumps({'header': {'action': action, 'task_id': task_id,
                                     'streaming': 'duplex'}, 'payload': payload})

    try:
        async with asyncio.timeout(20):
            async with connect(endpoint, additional_headers={
                    'Authorization': 'Bearer ' + config.api_key},
                    open_timeout=10, close_timeout=1, max_size=4 * 1024 * 1024) as ws:
                await ws.send(packet('run-task', {
                    'task_group': 'audio', 'task': 'tts', 'function': 'SpeechSynthesizer',
                    'model': config.model, 'parameters': {
                        'text_type': 'PlainText', 'voice': voice, 'format': 'pcm',
                        'sample_rate': rate, 'volume': 50, 'rate': 1.0, 'pitch': 1.0},
                    'input': {}}))
                task_started = False
                async for message in ws:
                    if isinstance(message, bytes):
                        if not task_started:
                            raise RuntimeError('百炼在任务开始前返回了音频')
                        if first_ms is None:
                            first_ms = round((time.monotonic() - started) * 1000)
                        pcm.extend(message)
                        if len(pcm) > rate * 2 * 60:
                            raise RuntimeError('百炼返回音频超过 60 秒限制')
                        continue
                    event = json.loads(message)
                    header = event.get('header', {})
                    if header.get('task_id') != task_id:
                        raise RuntimeError('百炼返回的任务 ID 不匹配')
                    kind = header.get('event')
                    if kind == 'task-failed':
                        # Never expose arbitrary provider messages or echoed credentials.
                        code = str(header.get('error_code', 'unknown'))
                        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code) or config.api_key in code:
                            code = 'unknown'
                        raise RuntimeError('百炼 TTS 失败：' + code)
                    if kind == 'task-started' and not task_started:
                        task_started = True
                        await ws.send(packet('continue-task', {'input': {'text': text}}))
                        await ws.send(packet('finish-task', {'input': {}}))
                    elif kind == 'task-finished':
                        if not pcm or len(pcm) % 2:
                            raise RuntimeError('百炼未返回有效 PCM16 音频')
                        count = event.get('payload', {}).get('usage', {}).get('characters')
                        if isinstance(count, (int, float)):
                            units = {'characters': count}
                        out = io.BytesIO()
                        with wave.open(out, 'wb') as wav:
                            wav.setnchannels(1)
                            wav.setsampwidth(2)
                            wav.setframerate(rate)
                            wav.writeframes(pcm)
                        status = 'ok'
                        return out.getvalue()
                raise RuntimeError('百炼连接在合成完成前关闭')
    except asyncio.CancelledError:
        status = 'cancelled'
        raise
    finally:
        usage(record(config,'tts',started,status,units,request_id=task_id,
                     input_scale={'text_characters':len(text)},output_audio_seconds=len(pcm)/(rate*2),
                     first_audio_ms=first_ms,model_version=None))
