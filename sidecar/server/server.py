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

    @staticmethod
    def _resolve_tokenizer_dir(model_subdir: Path) -> str:
        """Resolve the tokenizer DIRECTORY path for sherpa_onnx.

        sherpa_onnx.OfflineRecognizer.from_qwen3_asr(tokenizer=...) expects
        a DIRECTORY containing vocab.json (the tokenizer/ folder),
        NOT a single tokens.txt file.
        """
        tokenizer_dir = model_subdir / 'tokenizer'
        if tokenizer_dir.is_dir() and (tokenizer_dir / 'vocab.json').exists():
            return str(tokenizer_dir)
        # Fallback: if vocab.json is at the model root
        if (model_subdir / 'vocab.json').exists():
            return str(model_subdir)
        # Last resort: return expected path so error message is clear
        return str(tokenizer_dir)

    def _load_config(self):
        """Load configuration from config file or environment."""
        import os
        self.model_type = os.environ.get('CW_MODEL_TYPE', 'qwen_asr')
        model_dir = os.environ.get('CW_MODEL_DIR', '')

        # Auto-detect: when CW_MODEL_DIR is empty (typical for bundled .app),
        # search the script directory's grandparent (project root or _up_/)
        # plus a couple of macOS user-data locations.
        if not model_dir:
            base_script_dir = Path(__file__).resolve().parent.parent
            candidates = [
                base_script_dir / 'models',
                Path.home() / 'Library' / 'Application Support' / 'caps-writer-desktop' / 'models',
                Path.home() / 'Documents' / 'caps-writer-desktop' / 'models',
            ]
            for c in candidates:
                try:
                    if c.exists() and any(c.iterdir()):
                        model_dir = str(c)
                        print(f"[Server] Auto-detected model directory: {model_dir}", flush=True)
                        break
                except OSError:
                    continue

        config = {}
        if model_dir:
            base = Path(model_dir)

            # Detect GGUF model (e.g. Qwen3-ASR-1.7B with .gguf file)
            # Search for .gguf files in subdirectories
            gguf_subdir = None
            for subdir in sorted(base.iterdir()):
                if subdir.is_dir() and any(f.suffix == '.gguf' for f in subdir.iterdir() if f.is_file()):
                    gguf_subdir = subdir
                    break

            if gguf_subdir and self.model_type in ('qwen_asr', 'qwen3-asr'):
                print(f"[Server] Detected GGUF model: {gguf_subdir}", flush=True)
                config = {
                    'model_dir': str(gguf_subdir),
                }
            else:
                # sherpa-onnx ONNX model (0.6B int8)
                model_subdir = base / 'sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25'
                tokenizer_path = self._resolve_tokenizer_dir(model_subdir)
                config = {
                    'qwen_asr': {
                        'conv_frontend': str(model_subdir / 'conv_frontend.onnx'),
                        'encoder': str(model_subdir / 'encoder.int8.onnx'),
                        'decoder': str(model_subdir / 'decoder.int8.onnx'),
                        'tokenizer': tokenizer_path,
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
        elif 'Mock' in str(type(self.engine)):
            print(f"[Server] WARNING: Using mock engine (sherpa-onnx not available). Real recognition will return canned demo text only.", flush=True)
            print(f"[Server] To enable real ASR: pip install --break-system-packages sherpa_onnx  (Python 3.13.12 here)", flush=True)
        else:
            print(f"[Server] ERROR: Real engine {self.model_type} load FAILED (see [ASR] line above for traceback). Real recognition will NOT work.", flush=True)

        # Try to start WebSocket server
        try:
            import websockets
        except ImportError:
            print(f"[Server] FATAL: 'websockets' package is not installed.", flush=True)
            print(f"[Server] Please install it: pip install websockets", flush=True)
            print(f"[Server] Or: pip install -r sidecar/requirements.txt", flush=True)
            print(f"[Server] Exiting.", flush=True)
            return

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
            self.engine = create_engine(self.model_type, self._load_config())
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
