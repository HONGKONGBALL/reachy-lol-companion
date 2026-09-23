import asyncio
import io
import json
import wave

import pytest

from reachy_lol import dashscope_asr
from reachy_lol.model_config import ModelConfig


def fixture_wav(rate=16000, channels=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b'\x10\0' * (rate // 10) * channels)
    return out.getvalue()


def test_pcm_conversion_and_truncated_audio():
    pcm, rate, duration = dashscope_asr.pcm16(fixture_wav(24000, 2))
    assert (len(pcm), rate, duration) == (3200, 16000, .1)
    assert pcm == b'\x10\0' * 1600
    with pytest.raises(ValueError, match='不完整'):
        dashscope_asr.pcm16(fixture_wav()[:-10])


@pytest.mark.parametrize('scenario', ['success', 'silence', 'failure', 'wrong_task', 'cancel'])
def test_asr_final_sentences_and_cancellation(monkeypatch, scenario):
    config = ModelConfig('https://dashscope.aliyuncs.com/api/v1', 'asr-fake-key', 'fun-asr-realtime')
    rows = []
    entered = asyncio.Event()

    class Socket:
        closed = False
        def __init__(self):
            self.sent = []
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            self.closed = True
        async def send(self, message):
            self.sent.append(message if isinstance(message, bytes) else json.loads(message))
        async def events(self):
            task_id = self.sent[0]['header']['task_id']
            def event(kind, sentence=None, **header):
                return json.dumps({'header': {'task_id': task_id, 'event': kind, **header},
                    'payload': {'output': {'sentence': sentence or {}}, 'usage': {'duration': 1}}})
            if scenario == 'wrong_task':
                yield event('task-started', task_id='other')
                return
            yield event('task-started')
            assert self.sent[0]['payload']['task'] == 'asr'
            assert self.sent[1] == b'\x10\0' * 1600
            assert self.sent[-1]['header'] == {'action': 'finish-task', 'task_id': task_id, 'streaming': 'duplex'}
            entered.set()
            if scenario == 'cancel':
                await asyncio.Event().wait()
            if scenario == 'failure':
                yield event('task-failed', error_code='Denied', error_message='asr-fake-key')
                return
            # Partial text and heartbeat must never enter the chat context.
            yield event('result-generated', {'sentence_id': 1, 'text': '错误中间结果', 'sentence_end': False})
            yield event('result-generated', {'sentence_id': 0, 'text': '心跳', 'sentence_end': True, 'heartbeat': True})
            if scenario == 'success':
                yield event('result-generated', {'sentence_id': 2, 'text': '一起玩。', 'sentence_end': True})
                for _ in range(2):
                    yield event('result-generated', {'sentence_id': 1, 'text': '你好，', 'sentence_end': True})
            yield event('task-finished')
        def __aiter__(self):
            return self.events()

    socket = Socket()
    def connect(url, **kwargs):
        assert url == 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
        assert kwargs['additional_headers']['Authorization'] == 'Bearer asr-fake-key'
        return socket
    monkeypatch.setattr(dashscope_asr, 'connect', connect)
    async def run():
        task = asyncio.create_task(dashscope_asr.transcribe(config, fixture_wav(), rows.append))
        if scenario == 'cancel':
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif scenario in ('failure', 'wrong_task'):
            with pytest.raises(RuntimeError) as error:
                await task
            assert 'asr-fake-key' not in str(error.value)
        else:
            assert await task == ('你好，一起玩。' if scenario == 'success' else '')
    asyncio.run(run())
    assert socket.closed
    assert len(rows) == 1
    assert rows[0]['status'] == ('ok' if scenario in ('success', 'silence') else
                                 'cancelled' if scenario == 'cancel' else 'failed')
    assert all(s not in json.dumps(rows, ensure_ascii=False) for s in ('asr-fake-key', '你好', '错误中间结果'))
