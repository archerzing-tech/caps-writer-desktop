"""
Communication protocol between Tauri and ASR sidecar.
Uses JSON messages over stdin/stdout or WebSocket.
"""

import json
import base64
import struct
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class AudioMessage:
    """Audio data from Tauri to ASR server."""
    task_id: str
    source: str  # 'mic' or 'file'
    data_base64: str  # base64-encoded float32 PCM
    is_final: bool
    time_start: float
    seg_duration: float = 15.0
    seg_overlap: float = 2.0
    context: str = ''
    language: str = 'auto'

    def decode_audio(self):
        """Decode base64 audio data to float32 numpy array."""
        raw = base64.b64decode(self.data_base64)
        count = len(raw) // 4
        fmt = f'<{count}f'
        return struct.unpack(fmt, raw)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**{k: v for k, v in data.items()
                     if k in cls.__dataclass_fields__})


@dataclass
class RecognitionResult:
    """Recognition result from ASR server to Tauri."""
    task_id: str
    is_final: bool
    duration: float
    time_start: float
    time_submit: float
    time_complete: float
    text: str
    text_accu: str = ''
    tokens: list = None
    timestamps: list = None

    def to_dict(self):
        d = asdict(self)
        d['type'] = 'recognition'
        return d

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**{k: v for k, v in data.items()
                     if k in cls.__dataclass_fields__})


@dataclass
class StatusMessage:
    """Server status update."""
    status: str  # 'ready', 'loading', 'error', 'busy'
    message: str = ''

    def to_dict(self):
        d = asdict(self)
        d['type'] = 'status'
        return d


def create_message(msg_type: str, **kwargs):
    """Create a JSON-serializable message."""
    msg = {'type': msg_type, **kwargs}
    return json.dumps(msg, ensure_ascii=False) + '\n'
