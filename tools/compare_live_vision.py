"""Compare two authorized providers on identical real, masked frames; no playback."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from reachy_lol.capture import Capture, windows
from reachy_lol.cloud import Cloud
from reachy_lol.core import Frame
from reachy_lol.model_config import model_config


async def main():
    load_dotenv()
    original = model_config('vision')
    asr = model_config('asr')
    if urlsplit(asr.base_url).hostname != 'dashscope.aliyuncs.com':
        raise RuntimeError('Expected the previously authorized Dashscope host')
    capture = Capture()
    choices = [w for w in windows() if w['is_game']]
    if len(choices) != 1:
        raise RuntimeError('Exactly one live game window is required')
    capture.select(choices[0]['hwnd'])
    frames = []
    for index in range(2):
        if index:
            await asyncio.sleep(.6)
        jpeg = capture.grab()
        frames.append(Frame(uuid.uuid4().hex, time.monotonic(), jpeg,
                            window_id=capture.hwnd, width=capture.width, height=capture.height))
    report = {'actual_game_frames': True, 'same_frames_for_both': True,
              'frame_hashes': [hashlib.sha256(f.jpeg).hexdigest() for f in frames], 'results': []}
    saved = {key: os.environ.get(key) for key in ('VISION_BASE_URL', 'VISION_API_KEY', 'VISION_MODEL')}
    try:
        for name, base, key, model in [
            ('dashscope', 'https://dashscope.aliyuncs.com/compatible-mode/v1', asr.api_key, 'qwen3-vl-flash'),
            ('existing', original.base_url, original.api_key, original.model),
        ]:
            os.environ.update(VISION_BASE_URL=base, VISION_API_KEY=key, VISION_MODEL=model)
            usage = []
            cloud = Cloud(usage.append)
            request = cloud.request
            async def tuned(path, kind, **kwargs):
                if name == 'dashscope':
                    kwargs['json'].update(enable_thinking=False, max_tokens=350)
                return await request(path, kind, **kwargs)
            cloud.request = tuned
            started = time.monotonic()
            row = {'provider': name, 'model': model}
            try:
                result = await cloud.safety(frames)
                row['result'] = result.model_dump()
            except Exception as exc:
                row['error'] = type(exc).__name__
                if isinstance(exc, RuntimeError) and 'HTTP' in str(exc):
                    row['error'] = str(exc)
            finally:
                row['elapsed_ms'] = round((time.monotonic()-started)*1000)
                row['usage'] = usage
                await cloud.client.aclose()
            report['results'].append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='usage'}, ensure_ascii=False), flush=True)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Path('evidence/live-vision-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
