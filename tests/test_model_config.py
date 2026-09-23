import asyncio
import json

import httpx
import pytest

from reachy_lol.cloud import Cloud, Reply
from reachy_lol.model_config import CONFIG_KEYS, KINDS, model_config


@pytest.fixture(autouse=True)
def clean_model_environment(monkeypatch):
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_shared_defaults_and_partial_override(monkeypatch):
    monkeypatch.setenv('MODEL_BASE_URL', 'https://shared.invalid/v1/')
    monkeypatch.setenv('MODEL_API_KEY', 'shared-secret')
    monkeypatch.setenv('CHAT_MODEL', 'chat-model')
    assert model_config('chat').configured
    assert model_config('chat').base_url == 'https://shared.invalid/v1'
    monkeypatch.setenv('CHAT_BASE_URL', 'https://other.invalid/v1')
    assert not model_config('chat').configured
    assert model_config('chat').api_key == ''
    monkeypatch.setenv('CHAT_API_KEY', 'other-secret')
    assert model_config('chat').configured
    monkeypatch.setenv('CHAT_BASE_URL', '')
    assert not model_config('chat').configured


@pytest.mark.parametrize('url', ['http://cloud.invalid/v1', 'https://',
                               'https://user:secret@cloud.invalid/v1'])
def test_invalid_endpoint_is_not_configured(monkeypatch, url):
    monkeypatch.setenv('TTS_BASE_URL', url)
    monkeypatch.setenv('TTS_API_KEY', 'test-key')
    monkeypatch.setenv('TTS_MODEL', 'test-model')
    assert not model_config('tts').configured


def test_all_operations_use_their_own_endpoint_and_key(monkeypatch):
    for kind in KINDS:
        monkeypatch.setenv(f'{kind.upper()}_BASE_URL', f'https://{kind}.invalid/v1/')
        monkeypatch.setenv(f'{kind.upper()}_API_KEY', f'{kind}-secret')
        monkeypatch.setenv(f'{kind.upper()}_MODEL', f'{kind}-model')
    monkeypatch.setenv('VOICE_VELVET', 'custom-voice-id')
    usage, calls = [], []

    def handle(request):
        kind = request.url.host.split('.')[0]
        calls.append(kind)
        assert request.headers['authorization'] == f'Bearer {kind}-secret'
        if kind == 'asr':
            assert request.url.path == '/v1/audio/transcriptions'
            assert b'asr-model' in request.content
            assert b'owner.wav' in request.content
            return httpx.Response(200, json={'text': '测试转写'})
        body = json.loads(request.content)
        assert body['model'] == f'{kind}-model'
        if kind == 'tts':
            assert request.url.path == '/v1/audio/speech'
            assert body['voice'] == 'custom-voice-id'
            assert body['response_format'] == 'wav'
            return httpx.Response(200, content=b'RIFF-test', headers={'Content-Type': 'audio/wav'})
        assert request.url.path == '/v1/chat/completions'
        return httpx.Response(200, json={'choices': [{'message': {'content':
            '{"text":"测试", "motion":"nod", "evidence":[]}'}}]})

    async def run():
        cloud = Cloud(usage.append)
        await cloud.client.aclose()
        cloud.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            for kind in ('vision', 'chat'):
                assert (await cloud.structured(kind, 'test', 'test', Reply)).text == '测试'
            assert await cloud.asr(b'RIFF-test') == '测试转写'
            assert await cloud.tts('测试', 'aqi', 'velvet') == b'RIFF-test'
            # Configuration reload takes effect without rebuilding the HTTP client.
            monkeypatch.setenv('TTS_API_KEY', '')
            with pytest.raises(RuntimeError, match='TTS_BASE_URL'):
                await cloud.tts('测试', 'aqi', 'velvet')
        finally:
            await cloud.client.aclose()

    asyncio.run(run())
    assert calls == list(KINDS)
    assert all('secret' not in json.dumps(row) for row in usage)
