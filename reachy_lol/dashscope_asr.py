"""Fun-ASR WebSocket adapter for bounded utterances from the local VAD."""
import asyncio
import io
import json
import re
import time
import uuid
import wave
from urllib.parse import urlsplit, urlunsplit

import numpy as np
from websockets.asyncio.client import connect
from .usage import record


def pcm16(wav):
    if len(wav) > 12 * 1024 * 1024:
        raise ValueError('ASR 音频文件过大')
    with wave.open(io.BytesIO(wav), 'rb') as source:
        rate, channels, frames = source.getframerate(), source.getnchannels(), source.getnframes()
        if (source.getsampwidth() != 2 or source.getcomptype() != 'NONE' or
                channels not in (1, 2) or not 8000 <= rate <= 48000 or
                not 0 < frames <= rate * 30):
            raise ValueError('ASR 需要不超过 30 秒的单／双声道 PCM16 WAV')
        raw = source.readframes(frames)
    if len(raw) != frames * channels * 2:
        raise ValueError('ASR WAV 音频不完整')
    if channels == 1 and rate in (8000, 16000):
        return raw, rate, frames / rate
    samples = np.frombuffer(raw, dtype='<i2').reshape(-1, channels).mean(axis=1)
    count = round(frames * 16000 / rate)
    samples = np.interp(np.arange(count) * rate / 16000, np.arange(frames), samples)
    return np.clip(np.rint(samples), -32768, 32767).astype('<i2').tobytes(), 16000, frames / rate


async def transcribe(config, wav, usage):
    if not config.configured:
        raise RuntimeError('请配置完整的 ASR_BASE_URL / ASR_API_KEY / ASR_MODEL')
    url = urlsplit(config.base_url)
    if url.path.rstrip('/') != '/api/v1':
        raise RuntimeError('百炼 ASR_BASE_URL 须使用 HTTPS 地址并以 /api/v1 结尾')
    audio, rate, duration = pcm16(wav)
    endpoint = urlunsplit(('wss', url.netloc, '/api-ws/v1/inference', '', ''))
    task_id = uuid.uuid4().hex
    start = time.monotonic()
    status, units, sentences = 'failed', {}, {}

    def packet(action, payload):
        return json.dumps({'header': {'action': action, 'task_id': task_id,
                                     'streaming': 'duplex'}, 'payload': payload})

    try:
        async with asyncio.timeout(20):
            async with connect(endpoint, additional_headers={
                    'Authorization': 'Bearer ' + config.api_key},
                    open_timeout=10, close_timeout=1, max_size=1024 * 1024) as ws:
                await ws.send(packet('run-task', {'task_group': 'audio', 'task': 'asr',
                    'function': 'recognition', 'model': config.model,
                    'parameters': {'format': 'pcm', 'sample_rate': rate}, 'input': {}}))
                task_started = False
                async for message in ws:
                    event = json.loads(message)
                    header = event.get('header', {})
                    if header.get('task_id') != task_id:
                        raise RuntimeError('百炼 ASR 返回的任务 ID 不匹配')
                    kind = header.get('event')
                    if kind == 'task-failed':
                        code = str(header.get('error_code', 'unknown'))
                        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code) or config.api_key in code:
                            code = 'unknown'
                        raise RuntimeError('百炼 ASR 失败：' + code)
                    if kind == 'task-started' and not task_started:
                        task_started = True
                        # Upload a completed local utterance in 100 ms binary packets.
                        size = rate // 10 * 2
                        for offset in range(0, len(audio), size):
                            await ws.send(audio[offset:offset + size])
                            await asyncio.sleep(0)  # allow cancellation during upload
                        await ws.send(packet('finish-task', {'input': {}}))
                    elif kind == 'result-generated':
                        payload = event.get('payload', {})
                        sentence = payload.get('output', {}).get('sentence', {})
                        if sentence.get('heartbeat') or not sentence.get('sentence_end'):
                            continue
                        if not task_started:
                            raise RuntimeError('百炼 ASR 在任务开始前返回结果')
                        sentence_id = sentence.get('sentence_id', sentence.get('begin_time'))
                        if not isinstance(sentence_id, int) or not isinstance(sentence.get('text'), str):
                            raise RuntimeError('百炼 ASR 返回了无效的分句结果')
                        sentences[sentence_id] = sentence['text']
                        if sum(map(len, sentences.values())) > 4000:
                            raise RuntimeError('百炼 ASR 返回文本过长')
                        billed = (payload.get('usage') or {}).get('duration')
                        if isinstance(billed, (int, float)):
                            units['duration'] = billed
                    elif kind == 'task-finished':
                        if not task_started:
                            raise RuntimeError('百炼 ASR 未启动任务')
                        status = 'ok'
                        # Silence may legitimately produce no final sentences.
                        return ''.join(sentences[key] for key in sorted(sentences)).strip()
                raise RuntimeError('百炼连接在识别完成前关闭')
    except asyncio.CancelledError:
        status = 'cancelled'
        raise
    finally:
        usage(record(config,'asr',start,status,units,request_id=task_id,
                     input_audio_seconds=round(duration,3),input_scale={'audio_bytes':len(audio)},
                     model_version=None))
