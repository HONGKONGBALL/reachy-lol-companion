"""Resolve model endpoints without sharing credentials across provider overrides."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

KINDS = ('vision', 'chat', 'asr', 'tts')
CONFIG_KEYS = ('MODEL_BASE_URL', 'MODEL_API_KEY', 'TTS_PROVIDER', 'ASR_PROVIDER') + tuple(
    f'{kind.upper()}_{suffix}' for kind in KINDS
    for suffix in ('BASE_URL', 'API_KEY', 'MODEL')
)


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def configured(self):
        try:
            url = urlsplit(self.base_url)
            valid_url = url.scheme == 'https' and bool(url.hostname) and not (
                url.username or url.password or url.query or url.fragment)
        except ValueError:
            valid_url = False
        return bool(valid_url and self.api_key and self.model)


def model_config(kind):
    if kind not in KINDS:
        raise ValueError('未知模型用途')
    prefix = kind.upper()
    get = lambda key: os.getenv(key, '').strip()
    base, key = get(f'{prefix}_BASE_URL'), get(f'{prefix}_API_KEY')
    # Independent overrides require their own credentials; do not leak a shared key.
    if not base and not key:
        base, key = get('MODEL_BASE_URL'), get('MODEL_API_KEY')
    return ModelConfig(base.rstrip('/'), key, get(f'{prefix}_MODEL'))
