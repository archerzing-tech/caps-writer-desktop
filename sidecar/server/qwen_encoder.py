"""
Qwen3 Audio Encoder using ONNX Runtime.
Adapted from CapsWriter-Offline (HaujetZhao/CapsWriter-Offline).
Takes raw audio -> Mel spectrogram -> ONNX Frontend -> ONNX Backend -> audio embeddings.
"""
import os
import time
import numpy as np
import onnxruntime as ort


class FastWhisperMel:
    """Pure-numpy Mel spectrogram extractor (no librosa/numba dependency)."""
    def __init__(self, n_mels=128, sr=16000, n_fft=400):
        self.n_fft = n_fft
        self.hop_length = 160
        self.n_mels = n_mels
        self.filters = self._generate_filters(sr, n_fft, n_mels, 0, 8000, "slaney", "slaney")
        self.window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)

    @staticmethod
    def _hz_to_mel(freq, scale):
        if scale == "htk":
            return 2595.0 * np.log10(1.0 + (freq / 700.0))
        f_min_sl, f_sp_sl = 0.0, 200.0 / 3
        mels = (freq - f_min_sl) / f_sp_sl
        min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
        min_log_mel = (min_log_hz - f_min_sl) / f_sp_sl
        if isinstance(freq, np.ndarray):
            mask = freq >= min_log_hz
            mels[mask] = min_log_mel + np.log(freq[mask] / min_log_hz) / logstep
        elif freq >= min_log_hz:
            mels = min_log_mel + np.log(freq / min_log_hz) / logstep
        return mels

    @staticmethod
    def _mel_to_hz(mels, scale):
        if scale == "htk":
            return 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
        f_min_sl, f_sp_sl = 0.0, 200.0 / 3
        freqs = f_min_sl + f_sp_sl * mels
        min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
        min_log_mel = (min_log_hz - f_min_sl) / f_sp_sl
        if isinstance(mels, np.ndarray):
            mask = mels >= min_log_mel
            freqs[mask] = min_log_hz * np.exp(logstep * (mels[mask] - min_log_mel))
        elif mels >= min_log_mel:
            freqs = min_log_hz * np.exp(logstep * (mels - min_log_mel))
        return freqs

    def _generate_filters(self, sr, n_fft, n_mels, f_min, f_max, norm, mel_scale):
        n_freqs = n_fft // 2 + 1
        all_freqs = np.linspace(0, sr // 2, n_freqs)
        m_pts = np.linspace(self._hz_to_mel(f_min, mel_scale), self._hz_to_mel(f_max, mel_scale), n_mels + 2)
        f_pts = self._mel_to_hz(m_pts, mel_scale)
        f_diff = f_pts[1:] - f_pts[:-1]
        slopes = f_pts[np.newaxis, :] - all_freqs[:, np.newaxis]
        down_slopes = (-1.0 * slopes[:, :-2]) / f_diff[:-1]
        up_slopes = slopes[:, 2:] / f_diff[1:]
        fb = np.maximum(0, np.minimum(down_slopes, up_slopes))
        if norm == "slaney":
            enorm = 2.0 / (f_pts[2:n_mels + 2] - f_pts[:n_mels])
            fb *= enorm[np.newaxis, :]
        return fb.astype(np.float32)

    def __call__(self, audio: np.ndarray, dtype=np.float32) -> np.ndarray:
        pad_len = self.n_fft // 2
        y = np.pad(audio, pad_len, mode='reflect')
        num_frames = 1 + (len(y) - self.n_fft) // self.hop_length
        shape = (self.n_fft, num_frames)
        strides = (y.itemsize, self.hop_length * y.itemsize)
        frames = np.lib.stride_tricks.as_strided(y, shape=shape, strides=strides)
        stft_res = np.fft.rfft(frames * self.window[:, np.newaxis], axis=0)
        magnitudes = np.abs(stft_res) ** 2
        mel_spec = np.dot(self.filters.T, magnitudes)
        log_spec = np.log10(np.maximum(mel_spec, 1e-10))
        log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
        log_spec = (log_spec + 4.0) / 4.0
        n_frames_out = audio.shape[-1] // self.hop_length
        log_spec = log_spec[:, :n_frames_out]
        return log_spec.astype(dtype)


def _get_feat_extract_output_lengths(input_lengths):
    """Compute final frame count matching the ONNX frontend's internal logic."""
    input_lengths_leave = input_lengths % 100
    feat_lengths = (input_lengths_leave - 1) // 2 + 1
    output_lengths = ((feat_lengths - 1) // 2 + 1 - 1) // 2 + 1 + (input_lengths // 100) * 13
    return int(output_lengths)


class QwenAudioEncoder:
    """Qwen3 audio encoder: ONNX Frontend + ONNX Backend."""
    def __init__(self, frontend_path: str, backend_path: str, onnx_provider: str = 'CPU', verbose: bool = True):
        self.verbose = verbose

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3
        sess_opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        sess_opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        available_providers = ort.get_available_providers()
        providers = ['CPUExecutionProvider']
        if onnx_provider == 'CUDA' and 'CUDAExecutionProvider' in available_providers:
            providers.insert(0, 'CUDAExecutionProvider')
        elif onnx_provider == 'DML' and 'DmlExecutionProvider' in available_providers:
            providers.insert(0, 'DmlExecutionProvider')

        if self.verbose:
            print(f"[Encoder] Loading ONNX models (provider: {providers[0]})", flush=True)

        self.sess_fe = ort.InferenceSession(frontend_path, sess_options=sess_opts, providers=providers)
        self.sess_be = ort.InferenceSession(backend_path, sess_options=sess_opts, providers=providers)
        self.mel_extractor = FastWhisperMel()

        try:
            fe_input_type = self.sess_fe.get_inputs()[0].type
            self.input_dtype = np.float16 if 'float16' in fe_input_type else np.float32
        except Exception:
            self.input_dtype = np.float32

        # Warmup
        if self.verbose:
            print("[Encoder] Warming up...", flush=True)
        dummy = np.zeros(int(16000 * 2.0), dtype=np.float32)
        _ = self.encode(dummy)
        if self.verbose:
            print("[Encoder] Ready", flush=True)

    def _run_frontend(self, mel: np.ndarray) -> np.ndarray:
        T = mel.shape[1]
        pad_len = (100 - (T % 100)) % 100
        if pad_len > 0:
            mel = np.pad(mel, ((0, 0), (0, pad_len)), mode='constant')
        mel_input = mel[np.newaxis, ...]
        num_chunks = mel_input.shape[2] // 100
        fe_outputs = []
        for i in range(num_chunks):
            chunk = mel_input[:, :, i * 100: (i + 1) * 100]
            out = self.sess_fe.run(None, {"chunk_mel": chunk})[0]
            fe_outputs.append(out)
        hidden_states = np.concatenate(fe_outputs, axis=1)
        t_out = _get_feat_extract_output_lengths(T)
        return hidden_states[:, :t_out, :]

    def _run_backend(self, hidden_states: np.ndarray) -> np.ndarray:
        batch, seq_len, dim = hidden_states.shape
        mask = np.zeros((batch, 1, seq_len, seq_len), dtype=self.input_dtype)
        audio_embd = self.sess_be.run(None, {
            "hidden_states": hidden_states,
            "attention_mask": mask
        })[0]
        if audio_embd.shape[1] > seq_len:
            audio_embd = audio_embd[:, :seq_len, :]
        return audio_embd

    def encode(self, audio: np.ndarray) -> tuple:
        """Encode audio to embeddings. Returns (embedding [T, D], elapsed_seconds)."""
        t0 = time.time()
        mel = self.mel_extractor(audio, dtype=self.input_dtype)
        hidden_states = self._run_frontend(mel)
        audio_embd = self._run_backend(hidden_states)
        if audio_embd.ndim == 3:
            audio_embd = audio_embd[0]
        elapsed = time.time() - t0
        return audio_embd, elapsed
