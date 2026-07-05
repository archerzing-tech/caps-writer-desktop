"""
ASR Server - WebSocket-based speech recognition server.
Compatible with CapsWriter-Offline's protocol, adapted for CapsWriter Desktop.
"""

import asyncio
import json
import base64
import struct
import time
import sys
import signal
import numpy as np
from pathlib import Path

from .asr_engine import create_engine
from .protocol import AudioMessage, RecognitionResult, StatusMessage


class ASRServer:
    """
    WebSocket-based ASR server.
    
    Listens for audio data from Tauri, runs ASR, returns results.
    Falls back to mock engine if sherpa-onnx is not available.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 6016):
        self.host = host
        self.port = port
        self.engine = None
        self.model_type = 'qwen_asr'
        self._server = None
        self._tasks = {}

    def _load_config(self):
        """Load configuration from config file or environment."""
        import os
        self.model_type = os.environ.get('CW_MODEL_TYPE', 'qwen_asr')
        model_dir = os.environ.get('CW_MODEL_DIR', '')

        config = {}
        if model_dir:
            base = Path(model_dir)
            config = {
                'qwen_asr': {
                    'conv_frontend': str(base / 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25' / 'conv_frontend.onnx'),
                    'encoder': str(base / 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25' / 'encoder.int8.onnx'),
                    'decoder': str(base / 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25' / 'decoder.int8.onnx'),
                    'tokenizer': str(base / 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25' / 'tokenizer'),
                    'num_threads': 4,
                    'max_total_len': 1024,
                    'max_new_tokens': 512,
                },
            }.get(self.model_type, {})

        config['language'] = os.environ.get('CW_LANGUAGE', 'auto')
        config['provider'] = os.environ.get('CW_PROVIDER', 'cpu')
        return config

    async def start(self):
        """Start the WebSocket server."""
        # Load ASR engine
        config = self._load_config()
        self.engine = create_engine(self.model_type, config)
        
        print(f"[Server] Loading ASR engine: {self.model_type}...", flush=True)
        loaded = self.engine.load()
        
        if loaded:
            print(f"[Server] ASR engine loaded: {self.model_type}", flush=True)
        else:
            print(f"[Server] Using mock engine (sherpa-onnx not available)", flush=True)

        # Try to start WebSocket server
        try:
            import websockets
            self._server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
                ping_interval=None,
                max_size=10 * 1024 * 1024,  # 10MB max message
            )
            print(f"[Server] WebSocket listening on ws://{self.host}:{self.port}", flush=True)
            print(f"[Server] Ready", flush=True)
            await self._server.wait_closed()
        except ImportError:
            # Fallback to stdin/stdout protocol
            print(f"[Server] websockets not available, using stdio protocol", flush=True)
            print(f"[Server] Mock listening on stdio", flush=True)
            print(f"[Server] Ready", flush=True)
            await self._handle_stdio()

    async def stop(self):
        """Stop the server."""
        if self._server:
            self._server.close()
        if self.engine:
            self.engine.unload()

    async def _handle_client(self, websocket):
        """Handle a WebSocket client connection."""
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', '')

                if msg_type == 'audio':
                    result = await self._process_audio(data)
                    await websocket.send(json.dumps(result, ensure_ascii=False))
                elif msg_type == 'config':
                    await self._handle_config(data)
                    await websocket.send(json.dumps({
                        'type': 'status',
                        'status': 'configured',
                        'model': self.model_type,
                    }, ensure_ascii=False))
                elif msg_type == 'ping':
                    await websocket.send(json.dumps({'type': 'pong'}))

            except Exception as e:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': str(e),
                }, ensure_ascii=False))

    async def _handle_stdio(self):
        """Fallback: read JSON messages from stdin, write to stdout."""
        loop = asyncio.get_event_loop()

        def read_line():
            line = sys.stdin.readline()
            if not line:
                return None
            return line.strip()

        while True:
            line = await loop.run_in_executor(None, read_line)
            if line is None:
                break
            if not line:
                continue

            try:
                data = json.loads(line)
                msg_type = data.get('type', '')

                if msg_type == 'audio':
                    result = await self._process_audio(data)
                    sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
                    sys.stdout.flush()
                elif msg_type == 'config':
                    await self._handle_config(data)
                    sys.stdout.write(json.dumps({
                        'type': 'status', 'status': 'configured'
                    }, ensure_ascii=False) + '\n')
                    sys.stdout.flush()
                elif msg_type == 'ping':
                    sys.stdout.write(json.dumps({'type': 'pong'}) + '\n')
                    sys.stdout.flush()
                elif msg_type == 'shutdown':
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_msg = json.dumps({'type': 'error', 'message': str(e)})
                sys.stdout.write(error_msg + '\n')
                sys.stdout.flush()

    async def _process_audio(self, data: dict) -> dict:
        """Process audio data and return recognition result."""
        audio_msg = AudioMessage.from_dict(data)
        audio_float32 = audio_msg.decode_audio()
        audio_np = np.array(audio_float32, dtype=np.float32)

        time_submit = time.time()

        if self.engine:
            result = self.engine.recognize(audio_np, audio_msg.is_final)
        else:
            result = {'text': '', 'tokens': [], 'timestamps': []}

        time_complete = time.time()

        rec_result = RecognitionResult(
            task_id=audio_msg.task_id,
            is_final=audio_msg.is_final,
            duration=len(audio_np) / self.engine.sample_rate if self.engine else 0,
            time_start=audio_msg.time_start,
            time_submit=time_submit,
            time_complete=time_complete,
            text=result.get('text', ''),
            text_accu=result.get('text', ''),
            tokens=result.get('tokens', []),
            timestamps=result.get('timestamps', []),
        )

        return rec_result.to_dict()

    async def _handle_config(self, data: dict):
        """Handle configuration update."""
        config = data.get('config', {})
        new_model = config.get('model_type', '')
        if new_model and new_model != self.model_type:
            self.model_type = new_model
            if self.engine:
                self.engine.unload()
            self.engine = create_engine(self.model_type, {})
            self.engine.load()
            print(f"[Server] Switched to model: {self.model_type}", flush=True)


async def main():
    """Main entry point for the ASR sidecar server."""
    import os
    
    host = os.environ.get('CW_HOST', '127.0.0.1')
    port = int(os.environ.get('CW_PORT', '6016'))

    server = ASRServer(host=host, port=port)
    
    # Handle graceful shutdown
    stop_event = asyncio.Event()
    
    def shutdown():
        print("[Server] Shutting down...", flush=True)
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await server.start()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


if __name__ == '__main__':
    asyncio.run(main())
