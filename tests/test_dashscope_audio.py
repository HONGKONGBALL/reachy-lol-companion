import asyncio
import io
import json
import wave

import pytest

from reachy_lol import dashscope_audio
from reachy_lol.model_config import ModelConfig


@pytest.mark.parametrize('scenario', ['success', 'failure', 'cancel', 'empty', 'wrong_task'])
def test_cosyvoice_protocol(monkeypatch, scenario):
    entered = asyncio.Event()
    config = ModelConfig('https://dashscope.aliyuncs.com/api/v1', 'fake-key', 'cosyvoice-v3-flash')
    rows = []

    class Socket:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def send(self, packet):
            self.sent.append(json.loads(packet))

        async def events(self):
            task_id = self.sent[0]['header']['task_id']
            def event(kind, **fields):
                return json.dumps({'header': {'task_id': task_id, 'event': kind, **fields},
                                   'payload': {'usage': {'characters': 2}}})
            if scenario == 'wrong_task':
                yield event('task-started', task_id='other')
                return
            yield event('task-started')
            assert [p['header']['action'] for p in self.sent] == [
                'run-task', 'continue-task', 'finish-task']
            assert all(p['header']['task_id'] == task_id for p in self.sent)
            assert self.sent[1]['payload']['input']['text'] == '你好'
            entered.set()
            if scenario == 'cancel':
                await asyncio.Event().wait()
            if scenario == 'failure':
                yield event('task-failed', error_code='Denied', error_message='fake-key')
                return
            if scenario != 'empty':
                yield b'\0\0' * 240
                yield b'\1\0' * 240
            yield event('task-finished')

        def __aiter__(self):
            return self.events()

    sock = Socket()
    def connect(url, **kwargs):
        assert url == 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
        assert kwargs['additional_headers']['Authorization'] == 'Bearer fake-key'
        return sock
    monkeypatch.setattr(dashscope_audio, 'connect', connect)

    async def run():
        task = asyncio.create_task(dashscope_audio.synthesize(config, '你好', 'longanyang', rows.append))
        if scenario == 'cancel':
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif scenario == 'success':
            data = await task
            with wave.open(io.BytesIO(data), 'rb') as wav:
                assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (24000, 2, 1)
                assert wav.getnframes() == 480
        else:
            with pytest.raises(RuntimeError) as error:
                await task
            assert 'fake-key' not in str(error.value)
    asyncio.run(run())
    assert sock.closed
    assert len(rows) == 1
    assert rows[0]['status'] == ('ok' if scenario == 'success' else
                                  'cancelled' if scenario == 'cancel' else 'failed')
    assert 'fake-key' not in json.dumps(rows)
