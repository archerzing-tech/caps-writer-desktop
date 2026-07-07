"""
Qwen3-ASR GGUF Hybrid Engine.
ONNX encoder for audio embeddings + llama.cpp GGUF for LLM text generation.
Adapted from CapsWriter-Offline (HaujetZhao/CapsWriter-Offline).
"""
import os
import time
import codecs
import re
import numpy as np
from typing import Optional

from .qwen_encoder import QwenAudioEncoder
from . import llama_bindings as llama


class QwenAsrGgufEngine:
    """Hybrid ASR engine: ONNX encoder + GGUF LLM decoder."""

    def __init__(self, model_dir: str, onnx_provider: str = 'CPU', verbose: bool = True):
        self.model_dir = model_dir
        self.verbose = verbose
        self.encoder = None
        self.model = None
        self.ctx = None
        self.embedding_table = None
        self.n_embd = 0
        self.ID_IM_START = -1
        self.ID_IM_END = -1
        self.ID_AUDIO_START = -1
        self.ID_AUDIO_END = -1
        self.ID_ASR_TEXT = -1

        # Resolve file paths
        frontend = self._find_file(['qwen3_asr_encoder_frontend.onnx'])
        backend = self._find_file(['qwen3_asr_encoder_backend.onnx'])
        gguf = self._find_file([
            'qwen3_asr_llm.gguf',
            'qwen3_asr_llm.q5_k.gguf',
            'qwen3_asr_llm.q4_k.gguf',
            'Qwen3-ASR-1.7B.Q8_0.gguf',
            'Qwen3-ASR-1.7B.Q5_K_M.gguf',
            'Qwen3-ASR-1.7B.Q4_K_M.gguf',
        ])

        if not frontend or not backend or not gguf:
            raise FileNotFoundError(
                f"Missing model files in {model_dir}. "
                f"Need: qwen3_asr_encoder_frontend.onnx, qwen3_asr_encoder_backend.onnx, qwen3_asr_llm.gguf"
            )

        if verbose:
            print(f"[QwenGGUF] Model dir: {model_dir}", flush=True)
            print(f"[QwenGGUF]   Frontend: {os.path.basename(frontend)}", flush=True)
            print(f"[QwenGGUF]   Backend:  {os.path.basename(backend)}", flush=True)
            print(f"[QwenGGUF]   LLM:      {os.path.basename(gguf)}", flush=True)

        # 1. Load ONNX encoder
        self.encoder = QwenAudioEncoder(frontend, backend, onnx_provider=onnx_provider, verbose=verbose)

        # 2. Load GGUF LLM
        if verbose:
            print("[QwenGGUF] Loading GGUF LLM...", flush=True)
        t0 = time.time()
        self.model = llama.LlamaModel(gguf)
        self.embedding_table = llama.get_token_embeddings_gguf(gguf)
        self.ctx = llama.LlamaContext(self.model, n_ctx=1024, n_batch=1024)
        self.n_embd = self.model.n_embd

        # Cache special token IDs
        self.ID_IM_START = self.model.token_to_id('<|im_start|>')
        self.ID_IM_END = self.model.token_to_id('<|im_end|>')
        self.ID_AUDIO_START = self.model.token_to_id('<|audio_start|>')
        self.ID_AUDIO_END = self.model.token_to_id('<|audio_end|>')
        self.ID_ASR_TEXT = self.model.token_to_id('<asr_text>')

        if verbose:
            elapsed = time.time() - t0
            print(f"[QwenGGUF] LLM loaded in {elapsed:.1f}s (n_embd={self.n_embd})", flush=True)
            print(f"[QwenGGUF] Special tokens: im_start={self.ID_IM_START} im_end={self.ID_IM_END} "
                  f"audio_start={self.ID_AUDIO_START} audio_end={self.ID_AUDIO_END} asr_text={self.ID_ASR_TEXT}", flush=True)

    def _find_file(self, candidates):
        for name in candidates:
            path = os.path.join(self.model_dir, name)
            if os.path.isfile(path):
                return path
        return None

    def _build_prompt_embd(self, audio_embd, prefix_text='', context=None, language=None):
        """Build the full embedding sequence: [system] + [audio] + [instruction]."""
        def tk(t): return self.model.tokenize(t)

        # Block A: system prompt + user header + audio_start
        prefix_str = f"system\n{context or 'You are a helpful assistant.'}"
        prefix_tokens = [self.ID_IM_START] + tk(prefix_str) + [self.ID_IM_END] + \
                        [self.ID_IM_START] + tk("user\n") + [self.ID_AUDIO_START]

        # Block B: audio_end + instruction + assistant header + asr_text
        suffix_head = "assistant\n"
        if language:
            suffix_head += f"language {language}"
        suffix_tokens = [self.ID_AUDIO_END] + [self.ID_IM_END] + \
                        [self.ID_IM_START] + tk(suffix_head) + [self.ID_ASR_TEXT] + tk(prefix_text)

        n_pre = len(prefix_tokens)
        n_aud = audio_embd.shape[0]
        n_suf = len(suffix_tokens)
        total_embd = np.zeros((n_pre + n_aud + n_suf, self.n_embd), dtype=np.float32)

        total_embd[:n_pre] = self.embedding_table[prefix_tokens]
        total_embd[n_pre:n_pre + n_aud] = audio_embd
        total_embd[n_pre + n_aud:] = self.embedding_table[suffix_tokens]

        return total_embd

    def _decode(self, full_embd, temperature=0.4, max_new_tokens=512):
        """Run LLM prefill + generation. Returns generated text."""
        total_len = full_embd.shape[0]
        # Qwen3 multi-plane RoPE: 4x repeated position array
        pos_base = np.arange(0, total_len, dtype=np.int32)
        pos_arr = np.concatenate([pos_base, pos_base, pos_base, np.zeros(total_len, dtype=np.int32)])

        batch = llama.LlamaBatch(max(total_len * 4 + max_new_tokens, 16384), self.n_embd, 1)
        batch.set_embd(full_embd, pos=pos_arr)

        # Prefill
        self.ctx.clear_kv_cache()
        ret = self.ctx.decode(batch)
        if ret != 0:
            return ""

        # Generate
        sampler = llama.LlamaSampler(temperature=temperature)
        text_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        generated_text = ""
        generated_tokens = []

        last_token = sampler.sample(self.ctx)
        for _ in range(max_new_tokens):
            if last_token == self.model.eos_token or last_token == self.ID_IM_END:
                break

            ret = self.ctx.decode_token(last_token)
            if ret != 0:
                break

            generated_tokens.append(last_token)
            piece = text_decoder.decode(self.model.token_to_bytes(last_token))
            if piece:
                generated_text += piece

            # Circuit breaker: detect repetitive loops
            if len(generated_tokens) > 15:
                if len(set(generated_tokens[-15:])) <= 3:
                    break

            sampler.accept(last_token)
            last_token = sampler.sample(self.ctx)

        # Flush remaining bytes
        final = text_decoder.decode(b"", final=True)
        if final:
            generated_text += final

        sampler.free()
        del batch
        return generated_text

    def recognize(self, audio_np, is_final=True, language='auto'):
        """Full recognition pipeline: audio -> encode -> prompt build -> decode."""
        try:
            # 1. Encode audio
            audio_embd, enc_time = self.encoder.encode(audio_np)
            if self.verbose:
                print(f"[QwenGGUF] Encoded {len(audio_np)/16000:.1f}s audio in {enc_time:.2f}s", flush=True)

            # 2. Build prompt embedding
            lang_map = {'zh': 'Chinese', 'en': 'English', 'auto': None}
            mapped_lang = lang_map.get(language) if language else None
            full_embd = self._build_prompt_embd(audio_embd, language=mapped_lang)

            # 3. Decode
            t0 = time.time()
            text = self._decode(full_embd, temperature=0.4, max_new_tokens=512)
            dec_time = time.time() - t0

            if self.verbose:
                print(f"[QwenGGUF] Decoded in {dec_time:.2f}s: {text[:80]}...", flush=True)

            return {'text': text, 'tokens': [], 'timestamps': []}
        except Exception as e:
            import traceback
            print(f"[QwenGGUF] Recognition error:\n{traceback.format_exc()}", flush=True)
            return {'text': '', 'tokens': [], 'timestamps': []}

    def cleanup(self):
        """Explicitly free all llama.cpp resources."""
        if self.ctx:
            self.ctx.clear_kv_cache()
            del self.ctx
            self.ctx = None
        if self.model:
            del self.model
            self.model = None
        self.embedding_table = None
        self.encoder = None

    @property
    def sample_rate(self):
        return 16000
