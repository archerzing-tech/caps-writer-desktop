"""
ASR Engine abstraction layer.
Supports multiple backends: SenseVoice, Paraformer, Fun-ASR-Nano, Qwen3-ASR
"""

import time
import numpy as np
from typing import Optional, Callable


class ASREngine:
    """Abstract base for ASR engines."""

    def __init__(self, model_type: str = 'sensevoice', config: dict = None):
        self.model_type = model_type
        self.config = config or {}
        self._recognizer = None
        self._sample_rate = 16000

    def load(self) -> bool:
        raise NotImplementedError

    def recognize(self, audio: np.ndarray, is_final: bool = True) -> dict:
        raise NotImplementedError

    def unload(self):
        self._recognizer = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate


class SherpaOnnxEngine(ASREngine):
    """ASR engine using sherpa-onnx OfflineRecognizer."""

    def __init__(self, model_type: str = 'sensevoice', config: dict = None):
        super().__init__(model_type, config)
        self._model_paths = config or {}

    def load(self) -> bool:
        try:
            import sherpa_onnx
        except ImportError:
            print("[ASR] sherpa-onnx not installed. Using mock engine.")
            return False

        try:
            if self.model_type in ('qwen_asr', 'qwen3-asr'):
                self._recognizer = self._create_qwen_asr()
            elif self.model_type == 'sensevoice':
                self._recognizer = self._create_sensevoice()
            elif self.model_type == 'paraformer':
                self._recognizer = self._create_paraformer()
            elif self.model_type in ('fun_asr_nano', 'fun-asr-nano'):
                self._recognizer = self._create_funasr_nano()
            else:
                raise ValueError(f"Unknown model type: {self.model_type}")

            return self._recognizer is not None
        except Exception as e:
            print(f"[ASR] Failed to load model {self.model_type}: {e}")
            return False

    def _create_qwen_asr(self):
        """Create OfflineRecognizer from_qwen3_asr."""
        import sherpa_onnx
        paths = self._model_paths

        conv_frontend = paths.get('conv_frontend', '')
        encoder = paths.get('encoder', '')
        decoder = paths.get('decoder', '')
        tokenizer = paths.get('tokenizer', '') or paths.get('tokens', '')

        if not conv_frontend or not encoder or not decoder or not tokenizer:
            print(f"[ASR] Qwen3-ASR missing model files: conv_frontend={conv_frontend}, encoder={encoder}, decoder={decoder}, tokenizer={tokenizer}")
            return None

        return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=conv_frontend,
            encoder=encoder,
            decoder=decoder,
            tokenizer=tokenizer,
            num_threads=paths.get('num_threads', 4),
            sample_rate=16000,
            feature_dim=128,
            provider=paths.get('provider', 'cpu'),
            max_total_len=paths.get('max_total_len', 512),
            max_new_tokens=paths.get('max_new_tokens', 512),
            temperature=paths.get('temperature', 1e-6),
            top_p=paths.get('top_p', 0.8),
            seed=paths.get('seed', 42),
            hotwords=paths.get('hotwords', ''),
        )

    def _create_sensevoice(self):
        """Create OfflineRecognizer from_sense_voice."""
        import sherpa_onnx
        paths = self._model_paths

        # SenseVoice needs: model (single ONNX), tokens (tokens.txt)
        model = paths.get('model', '') or paths.get('encoder', '')
        tokens = paths.get('tokens', '')

        if not model or not tokens:
            print("[ASR] SenseVoice requires model and tokens files")
            return None

        try:
            # Use tokenizer.bpe.model for tokens if it's a sentencepiece model
            if tokens.endswith('.model'):
                return self._create_sensevoice_with_bpe(model, tokens, paths)
            else:
                return sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=model,
                    tokens=tokens,
                    num_threads=paths.get('num_threads', 4),
                    provider=paths.get('provider', 'cpu'),
                    language=paths.get('language', 'auto'),
                    use_itn=paths.get('use_itn', False),
                )
        except Exception as e:
            print(f"[ASR] SenseVoice load error, trying alternative: {e}")
            # Fallback: try with combined model if available
            alt_model = paths.get('decoder', '') or paths.get('ctc_model', model)
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=alt_model,
                tokens=tokens if not tokens.endswith('.model') else model,
                num_threads=paths.get('num_threads', 4),
                provider=paths.get('provider', 'cpu'),
            )

    def _create_sensevoice_with_bpe(self, model, bpe_model, paths):
        """Use SenseVoice with a sentencepiece BPE model.
        Falls back if sentencepiece is not available."""
        try:
            import sentencepiece as spm
            sp = spm.SentencePieceProcessor(model_file=bpe_model)
            tokens_txt = []
            for i in range(sp.vocab_size()):
                tokens_txt.append(sp.id_to_piece(i))
            import tempfile, os
            fd, tmp_path = tempfile.mkstemp(suffix='.txt')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                for t in tokens_txt:
                    f.write(t + '\n')
            import sherpa_onnx
            result = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model,
                tokens=tmp_path,
                num_threads=paths.get('num_threads', 4),
                provider=paths.get('provider', 'cpu'),
                language=paths.get('language', 'auto'),
            )
            # Don't clean up - the recognizer keeps a reference to the file path
            return result
        except Exception as e:
            print(f"[ASR] BPE tokens fallback failed: {e}")
            return None

    def _create_paraformer(self):
        import sherpa_onnx
        paths = self._model_paths
        return sherpa_onnx.OfflineRecognizer.from_paraformer(
            model=paths.get('model', ''),
            tokens=paths.get('tokens', ''),
            num_threads=paths.get('num_threads', 4),
            provider=paths.get('provider', 'cpu'),
            sample_rate=16000,
            feature_dim=80,
        )

    def _create_funasr_nano(self):
        import sherpa_onnx
        paths = self._model_paths
        return sherpa_onnx.OfflineRecognizer.from_funasr_nano(
            encoder_adaptor=paths.get('encoder_adaptor', ''),
            ctc=paths.get('ctc', ''),
            llm=paths.get('llm', ''),
            tokens=paths.get('tokens', ''),
            num_threads=paths.get('num_threads', 4),
            provider=paths.get('provider', 'cpu'),
        )

    def recognize(self, audio: np.ndarray, is_final: bool = True) -> dict:
        if self._recognizer is None:
            return {'text': '', 'tokens': [], 'timestamps': []}

        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, audio)

        self._recognizer.decode_stream(stream)

        # Result is available via stream.result (OfflineStream struct with .text)
        result = stream.result
        if hasattr(result, 'text'):
            text = result.text
        elif isinstance(result, dict):
            text = result.get('text', '')
        else:
            text = str(result)

        return {
            'text': text,
            'tokens': [],
            'timestamps': [],
        }


class MockEngine(ASREngine):
    """Mock engine for development/demo without actual model files."""

    def load(self) -> bool:
        print(f"[Mock] Loaded mock engine ({self.model_type})")
        return True

    def recognize(self, audio: np.ndarray, is_final: bool = True) -> dict:
        duration = len(audio) / self._sample_rate
        time.sleep(min(duration * 0.1, 0.5))

        texts = {
            'chinese': '这是一段语音识别的测试结果。离线语音识别引擎工作正常。',
            'english': 'This is a test of the speech recognition engine.',
            'auto': '语音识别测试完成。Speech recognition test completed.',
        }
        text = texts.get(self.config.get('language', 'auto'), texts['auto'])

        return {
            'text': text,
            'tokens': list(text),
            'timestamps': [i * 0.1 for i in range(len(text))],
        }


def create_engine(model_type: str = 'sensevoice', config: dict = None) -> ASREngine:
    """Factory: create the appropriate ASR engine."""
    try:
        import sherpa_onnx
        return SherpaOnnxEngine(model_type, config)
    except ImportError:
        print("[ASR] sherpa-onnx not available, using MockEngine")
        return MockEngine(model_type, config)
