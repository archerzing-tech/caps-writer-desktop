"""
llama.cpp ctypes bindings for Qwen3-ASR GGUF model loading and inference.
Adapted from CapsWriter-Offline (HaujetZhao/CapsWriter-Offline).
"""
import sys
import os
import ctypes
import codecs
import struct
import time
import numpy as np
from typing import List, Optional

try:
    import gguf
    from gguf.constants import GGML_QUANT_SIZES, GGMLQuantizationType
    HAS_GGUF = True
except ImportError:
    HAS_GGUF = False

# =========================================================================
# Type Definitions
# =========================================================================
llama_token = ctypes.c_int32
llama_pos = ctypes.c_int32
llama_seq_id = ctypes.c_int32


class llama_model_params(ctypes.Structure):
    _fields_ = [
        ("devices", ctypes.POINTER(ctypes.c_void_p)),
        ("tensor_buft_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int32),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.POINTER(ctypes.c_float)),
        ("progress_callback", ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_float, ctypes.c_void_p)),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("vocab_only", ctypes.c_bool),
        ("use_mmap", ctypes.c_bool),
        ("use_direct_io", ctypes.c_bool),
        ("use_mlock", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
    ]


class llama_context_params(ctypes.Structure):
    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_outputs_max", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int32),
        ("rope_scaling_type", ctypes.c_int32),
        ("pooling_type", ctypes.c_int32),
        ("attention_type", ctypes.c_int32),
        ("flash_attn_type", ctypes.c_int32),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int32),
        ("type_v", ctypes.c_int32),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.POINTER(ctypes.c_void_p)),
        ("n_samplers", ctypes.c_size_t),
        ("ctx_other", ctypes.c_void_p),
    ]


class llama_sampler_chain_params(ctypes.Structure):
    _fields_ = [("no_perf", ctypes.c_bool)]


class llama_logit_bias(ctypes.Structure):
    _fields_ = [
        ("token", llama_token),
        ("bias", ctypes.c_float),
    ]


class llama_batch(ctypes.Structure):
    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(llama_token)),
        ("embd", ctypes.POINTER(ctypes.c_float)),
        ("pos", ctypes.POINTER(llama_pos)),
        ("n_seq_id", ctypes.POINTER(ctypes.c_int32)),
        ("seq_id", ctypes.POINTER(ctypes.POINTER(llama_seq_id))),
        ("logits", ctypes.POINTER(ctypes.c_int8)),
    ]


# =========================================================================
# Global library references
# =========================================================================
_llama = None
_ggml = None
_ggml_base = None

# Function pointers
llama_model_default_params = None
llama_model_load_from_file = None
llama_model_free = None
llama_model_get_vocab = None
llama_model_n_embd = None
llama_context_default_params = None
llama_init_from_model = None
llama_free = None
llama_batch_init = None
llama_batch_free = None
llama_batch_get_one = None
llama_decode = None
llama_get_logits = None
llama_get_logits_ith = None
llama_get_embeddings = None
llama_tokenize = None
llama_vocab_n_tokens = None
llama_vocab_eos = None
llama_token_to_piece = None
llama_get_memory = None
llama_memory_clear = None
# Sampler
llama_sampler_chain_default_params = None
llama_sampler_chain_init = None
llama_sampler_chain_add = None
llama_sampler_init_greedy = None
llama_sampler_init_dist = None
llama_sampler_init_temp = None
llama_sampler_init_top_k = None
llama_sampler_init_top_p = None
llama_sampler_sample = None
llama_sampler_free = None
llama_sampler_init_min_p = None
llama_sampler_init_penalties = None
llama_sampler_accept = None

_initialized = False
_log_callback = None


def _bind_lib():
    """Bind all llama.cpp C API functions via ctypes."""
    global _llama, _ggml, _ggml_base
    global llama_model_default_params, llama_model_load_from_file, llama_model_free
    global llama_model_get_vocab, llama_model_n_embd
    global llama_context_default_params, llama_init_from_model, llama_free
    global llama_batch_init, llama_batch_free, llama_batch_get_one
    global llama_decode, llama_get_logits, llama_get_logits_ith, llama_get_embeddings
    global llama_tokenize, llama_vocab_n_tokens, llama_vocab_eos, llama_token_to_piece
    global llama_get_memory, llama_memory_clear
    global llama_sampler_chain_default_params, llama_sampler_chain_init, llama_sampler_chain_add
    global llama_sampler_init_greedy, llama_sampler_init_dist, llama_sampler_init_temp
    global llama_sampler_init_top_k, llama_sampler_init_top_p
    global llama_sampler_sample, llama_sampler_free
    global llama_sampler_init_min_p, llama_sampler_init_penalties, llama_sampler_accept

    lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llama")

    if sys.platform == "darwin":
        _ggml_base = ctypes.CDLL(os.path.join(lib_dir, "libggml-base.dylib"))
        _ggml = ctypes.CDLL(os.path.join(lib_dir, "libggml.dylib"))
        _llama = ctypes.CDLL(os.path.join(lib_dir, "libllama.dylib"))
    elif sys.platform == "win32":
        _ggml_base = ctypes.CDLL(os.path.join(lib_dir, "ggml-base.dll"))
        _ggml = ctypes.CDLL(os.path.join(lib_dir, "ggml.dll"))
        _llama = ctypes.CDLL(os.path.join(lib_dir, "llama.dll"))
    else:
        _ggml_base = ctypes.CDLL(os.path.join(lib_dir, "libggml-base.so"))
        _ggml = ctypes.CDLL(os.path.join(lib_dir, "libggml.so"))
        _llama = ctypes.CDLL(os.path.join(lib_dir, "libllama.so"))

    # Load all backends
    try:
        _ggml.ggml_backend_load_all.argtypes = []
        _ggml.ggml_backend_load_all.restype = None
        _ggml.ggml_backend_load_all()
    except AttributeError:
        pass

    _llama.llama_backend_init.argtypes = []
    _llama.llama_backend_init.restype = None
    _llama.llama_backend_init()

    # Suppress llama.cpp logging
    # IMPORTANT: store the callback reference as a module-level global to prevent
    # Python GC from collecting it while llama.cpp still holds the pointer.
    global _log_callback
    LOG_CB = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
    _log_callback = LOG_CB(lambda l, m, u: None)
    _llama.llama_log_set.argtypes = [LOG_CB, ctypes.c_void_p]
    _llama.llama_log_set.restype = None
    _llama.llama_log_set(_log_callback, None)

    # Model
    llama_model_default_params = _llama.llama_model_default_params
    llama_model_default_params.argtypes = []
    llama_model_default_params.restype = llama_model_params

    llama_model_load_from_file = _llama.llama_model_load_from_file
    llama_model_load_from_file.argtypes = [ctypes.c_char_p, llama_model_params]
    llama_model_load_from_file.restype = ctypes.c_void_p

    llama_model_free = _llama.llama_model_free
    llama_model_free.argtypes = [ctypes.c_void_p]
    llama_model_free.restype = None

    llama_model_get_vocab = _llama.llama_model_get_vocab
    llama_model_get_vocab.argtypes = [ctypes.c_void_p]
    llama_model_get_vocab.restype = ctypes.c_void_p

    llama_model_n_embd = _llama.llama_model_n_embd
    llama_model_n_embd.argtypes = [ctypes.c_void_p]
    llama_model_n_embd.restype = ctypes.c_int32

    # Context
    llama_context_default_params = _llama.llama_context_default_params
    llama_context_default_params.argtypes = []
    llama_context_default_params.restype = llama_context_params

    llama_init_from_model = _llama.llama_init_from_model
    llama_init_from_model.argtypes = [ctypes.c_void_p, llama_context_params]
    llama_init_from_model.restype = ctypes.c_void_p

    llama_free = _llama.llama_free
    llama_free.argtypes = [ctypes.c_void_p]
    llama_free.restype = None

    # Batch
    llama_batch_init = _llama.llama_batch_init
    llama_batch_init.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
    llama_batch_init.restype = llama_batch

    llama_batch_free = _llama.llama_batch_free
    llama_batch_free.argtypes = [llama_batch]
    llama_batch_free.restype = None

    llama_batch_get_one = _llama.llama_batch_get_one
    llama_batch_get_one.argtypes = [ctypes.POINTER(llama_token), ctypes.c_int32]
    llama_batch_get_one.restype = llama_batch

    # Decode
    llama_decode = _llama.llama_decode
    llama_decode.argtypes = [ctypes.c_void_p, llama_batch]
    llama_decode.restype = ctypes.c_int32

    # Logits
    llama_get_logits = _llama.llama_get_logits
    llama_get_logits.argtypes = [ctypes.c_void_p]
    llama_get_logits.restype = ctypes.POINTER(ctypes.c_float)

    llama_get_logits_ith = _llama.llama_get_logits_ith
    llama_get_logits_ith.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    llama_get_logits_ith.restype = ctypes.POINTER(ctypes.c_float)

    llama_get_embeddings = _llama.llama_get_embeddings
    llama_get_embeddings.argtypes = [ctypes.c_void_p]
    llama_get_embeddings.restype = ctypes.POINTER(ctypes.c_float)

    # Tokenize
    llama_tokenize = _llama.llama_tokenize
    llama_tokenize.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
        ctypes.POINTER(llama_token), ctypes.c_int32,
        ctypes.c_bool, ctypes.c_bool,
    ]
    llama_tokenize.restype = ctypes.c_int32

    # Vocab
    llama_vocab_n_tokens = _llama.llama_vocab_n_tokens
    llama_vocab_n_tokens.argtypes = [ctypes.c_void_p]
    llama_vocab_n_tokens.restype = ctypes.c_int32

    llama_vocab_eos = _llama.llama_vocab_eos
    llama_vocab_eos.argtypes = [ctypes.c_void_p]
    llama_vocab_eos.restype = llama_token

    llama_token_to_piece = _llama.llama_token_to_piece
    llama_token_to_piece.argtypes = [
        ctypes.c_void_p, llama_token, ctypes.c_char_p,
        ctypes.c_int32, ctypes.c_int32, ctypes.c_bool,
    ]
    llama_token_to_piece.restype = ctypes.c_int

    # Memory (KV Cache)
    llama_get_memory = _llama.llama_get_memory
    llama_get_memory.argtypes = [ctypes.c_void_p]
    llama_get_memory.restype = ctypes.c_void_p

    llama_memory_clear = _llama.llama_memory_clear
    llama_memory_clear.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    llama_memory_clear.restype = None

    # Sampler
    llama_sampler_chain_default_params = _llama.llama_sampler_chain_default_params
    llama_sampler_chain_default_params.argtypes = []
    llama_sampler_chain_default_params.restype = llama_sampler_chain_params

    llama_sampler_chain_init = _llama.llama_sampler_chain_init
    llama_sampler_chain_init.argtypes = [llama_sampler_chain_params]
    llama_sampler_chain_init.restype = ctypes.c_void_p

    llama_sampler_chain_add = _llama.llama_sampler_chain_add
    llama_sampler_chain_add.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    llama_sampler_chain_add.restype = None

    llama_sampler_init_greedy = _llama.llama_sampler_init_greedy
    llama_sampler_init_greedy.argtypes = []
    llama_sampler_init_greedy.restype = ctypes.c_void_p

    llama_sampler_init_dist = _llama.llama_sampler_init_dist
    llama_sampler_init_dist.argtypes = [ctypes.c_uint32]
    llama_sampler_init_dist.restype = ctypes.c_void_p

    llama_sampler_init_temp = _llama.llama_sampler_init_temp
    llama_sampler_init_temp.argtypes = [ctypes.c_float]
    llama_sampler_init_temp.restype = ctypes.c_void_p

    llama_sampler_init_top_k = _llama.llama_sampler_init_top_k
    llama_sampler_init_top_k.argtypes = [ctypes.c_int32]
    llama_sampler_init_top_k.restype = ctypes.c_void_p

    llama_sampler_init_top_p = _llama.llama_sampler_init_top_p
    llama_sampler_init_top_p.argtypes = [ctypes.c_float, ctypes.c_size_t]
    llama_sampler_init_top_p.restype = ctypes.c_void_p

    llama_sampler_sample = _llama.llama_sampler_sample
    llama_sampler_sample.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]
    llama_sampler_sample.restype = llama_token

    llama_sampler_free = _llama.llama_sampler_free
    llama_sampler_free.argtypes = [ctypes.c_void_p]
    llama_sampler_free.restype = None

    llama_sampler_init_min_p = _llama.llama_sampler_init_min_p
    llama_sampler_init_min_p.argtypes = [ctypes.c_float, ctypes.c_size_t]
    llama_sampler_init_min_p.restype = ctypes.c_void_p

    llama_sampler_init_penalties = _llama.llama_sampler_init_penalties
    llama_sampler_init_penalties.argtypes = [ctypes.c_int32, ctypes.c_float, ctypes.c_float, ctypes.c_float]
    llama_sampler_init_penalties.restype = ctypes.c_void_p

    llama_sampler_accept = _llama.llama_sampler_accept
    llama_sampler_accept.argtypes = [ctypes.c_void_p, llama_token]
    llama_sampler_accept.restype = None


def init():
    """Initialize llama.cpp library. Must be called once before any other operations."""
    global _initialized
    if _initialized:
        return

    lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llama")
    original_cwd = os.getcwd()

    # Change to lib dir so dynamic linker can find dependent dylibs
    os.chdir(lib_dir)
    os.environ['PATH'] = lib_dir + os.pathsep + os.environ.get('PATH', '')

    try:
        _bind_lib()
        _initialized = True
        print(f"[llama] Initialized successfully from {lib_dir}", flush=True)
    finally:
        os.chdir(original_cwd)


# =========================================================================
# High-level API
# =========================================================================

class LlamaModel:
    """GGUF model wrapper."""
    def __init__(self, path: str, n_gpu_layers: int = 0):
        params = llama_model_default_params()
        params.n_gpu_layers = n_gpu_layers
        self.ptr = llama_model_load_from_file(
            path.encode('utf-8') if isinstance(path, str) else path, params
        )
        if not self.ptr:
            raise RuntimeError(f"Failed to load GGUF model: {path}")

        self.vocab = llama_model_get_vocab(self.ptr)
        self.n_embd = llama_model_n_embd(self.ptr)
        self.eos_token = llama_vocab_eos(self.vocab)

    def tokenize(self, text: str, add_special: bool = False, parse_special: bool = True) -> List[int]:
        text_bytes = text.encode("utf-8")
        n_max = len(text_bytes) + 32
        tokens = (llama_token * n_max)()
        n = llama_tokenize(self.vocab, text_bytes, len(text_bytes), tokens, n_max, add_special, parse_special)
        return [tokens[i] for i in range(n)] if n >= 0 else []

    def token_to_bytes(self, token_id: int) -> bytes:
        buf = ctypes.create_string_buffer(256)
        n = llama_token_to_piece(self.vocab, token_id, buf, ctypes.sizeof(buf), 0, True)
        return buf.raw[:n] if n > 0 else b""

    def token_to_id(self, text: str) -> int:
        tokens = self.tokenize(text, add_special=False, parse_special=True)
        return tokens[0] if tokens else -1

    def detokenize(self, tokens: List[int]) -> str:
        if not tokens:
            return ""
        all_bytes = b"".join([self.token_to_bytes(tid) for tid in tokens])
        return all_bytes.decode('utf-8', errors='replace')

    def __del__(self):
        if hasattr(self, 'ptr') and self.ptr:
            llama_model_free(self.ptr)
            self.ptr = None


class LlamaContext:
    """Inference context wrapper."""
    def __init__(self, model: LlamaModel, n_ctx: int = 2048, n_batch: int = 4096):
        params = llama_context_default_params()
        params.n_ctx = n_ctx
        params.n_batch = n_batch
        params.n_ubatch = 256
        params.embeddings = False
        params.flash_attn_type = 0
        params.offload_kqv = False
        params.no_perf = True
        cpu_count = os.cpu_count() or 8
        params.n_threads = cpu_count
        params.n_threads_batch = cpu_count

        self.model = model
        self.ptr = llama_init_from_model(model.ptr, params)
        if not self.ptr:
            raise RuntimeError("Failed to create llama context")

    def decode(self, batch):
        struct = batch.struct if hasattr(batch, 'struct') else batch
        return llama_decode(self.ptr, struct)

    def decode_token(self, token_id: int) -> int:
        token_arr = (llama_token * 1)(token_id)
        batch = llama_batch_get_one(token_arr, 1)
        return llama_decode(self.ptr, batch)

    def get_logits(self):
        return llama_get_logits(self.ptr)

    def clear_kv_cache(self):
        mem = llama_get_memory(self.ptr)
        llama_memory_clear(mem, True)

    def __del__(self):
        if hasattr(self, 'ptr') and self.ptr:
            llama_free(self.ptr)
            self.ptr = None


class LlamaBatch:
    """Batch wrapper supporting embedding injection."""
    def __init__(self, n_tokens: int, embd_dim: int = 0, n_seq_max: int = 1):
        self.struct = llama_batch_init(n_tokens, embd_dim, n_seq_max)
        self.n_tokens_max = n_tokens

    def set_embd(self, data: np.ndarray, pos):
        n_tokens = data.shape[0]
        if n_tokens > self.n_tokens_max:
            raise ValueError(f"Batch overflow: {n_tokens} > {self.n_tokens_max}")

        if not data.flags['C_CONTIGUOUS']:
            data = np.ascontiguousarray(data)
        ctypes.memmove(self.struct.embd, data.ctypes.data, data.nbytes)

        if isinstance(pos, int):
            for i in range(n_tokens):
                self.struct.pos[i] = pos + i
        elif isinstance(pos, np.ndarray):
            if not pos.flags['C_CONTIGUOUS']:
                pos = np.ascontiguousarray(pos)
            ctypes.memmove(self.struct.pos, pos.ctypes.data, pos.nbytes)

        self.struct.n_tokens = n_tokens
        for i in range(n_tokens):
            self.struct.n_seq_id[i] = 1
            self.struct.seq_id[i][0] = 0
            self.struct.logits[i] = 1 if i == n_tokens - 1 else 0

    def __del__(self):
        if hasattr(self, 'struct'):
            llama_batch_free(self.struct)


class LlamaSampler:
    """Sampler wrapper."""
    def __init__(self, temperature: float = 0.4, seed: Optional[int] = None):
        if seed is None:
            seed = int(time.time()) % (2**31)
        sparams = llama_sampler_chain_default_params()
        self.ptr = llama_sampler_chain_init(sparams)

        if temperature > 0:
            llama_sampler_chain_add(self.ptr, llama_sampler_init_top_k(50))
            llama_sampler_chain_add(self.ptr, llama_sampler_init_temp(temperature))
            llama_sampler_chain_add(self.ptr, llama_sampler_init_dist(seed))
        else:
            llama_sampler_chain_add(self.ptr, llama_sampler_init_greedy())

    def sample(self, ctx, idx: int = -1) -> int:
        ctx_ptr = ctx.ptr if hasattr(ctx, 'ptr') else ctx
        return llama_sampler_sample(self.ptr, ctx_ptr, idx)

    def accept(self, token_id: int):
        llama_sampler_accept(self.ptr, token_id)

    def free(self):
        if hasattr(self, 'ptr') and self.ptr:
            llama_sampler_free(self.ptr)
            self.ptr = None

    def __del__(self):
        self.free()


# =========================================================================
# Embedding Table extraction from GGUF
# =========================================================================

class LlamaEmbeddingTable:
    """Dequantizing embedding table with table[ids] syntax."""
    def __init__(self, raw_data, qtype):
        self.raw_data = raw_data
        self.qtype = qtype

    def __len__(self):
        return self.raw_data.shape[0]

    def __getitem__(self, tokens):
        if self.raw_data.dtype in (np.float32, np.float16):
            return self.raw_data[tokens].astype(np.float32)
        if HAS_GGUF:
            from gguf.quants import dequantize
            return dequantize(self.raw_data[tokens], self.qtype.value)
        raise RuntimeError("gguf package required for dequantization")


def _skip_gguf_value(mm, offs, v_type):
    fixed = [1, 1, 2, 2, 4, 4, 4, 1, -1, -2, 8, 8, 8]
    val_len = fixed[v_type]
    if val_len > 0:
        return offs + val_len
    elif val_len == -1:
        slen = struct.unpack_from("<Q", mm, offs)[0]
        return offs + 8 + slen
    elif val_len == -2:
        itype, alen = struct.unpack_from("<IQ", mm, offs)
        offs += 12
        if itype == 8:
            for _ in range(alen):
                slen = struct.unpack_from("<Q", mm, offs)[0]
                offs += 8 + slen
        else:
            item_len = fixed[itype]
            if item_len > 0:
                offs += item_len * alen
            else:
                raise ValueError("Nested arrays not supported")
        return offs


def get_token_embeddings_gguf(model_path: str, target_tensor: str = "token_embd.weight"):
    """Extract token embedding table directly from GGUF file (< 50ms)."""
    if not HAS_GGUF:
        raise RuntimeError("gguf package required: pip install gguf")

    t_start = time.time()
    mm = np.memmap(model_path, mode='r')

    tensor_count, kv_count = struct.unpack_from("<QQ", mm, 8)
    offs = 24
    alignment = 32

    for _ in range(kv_count):
        key_len = struct.unpack_from("<Q", mm, offs)[0]
        offs += 8
        if key_len == 17 and mm[offs:offs+17].tobytes() == b'general.alignment':
            offs += 17
            v_type = struct.unpack_from("<I", mm, offs)[0]
            offs += 4
            if v_type == 4:
                alignment = struct.unpack_from("<I", mm, offs)[0]
                offs += 4
                continue
        else:
            offs += key_len
        v_type = struct.unpack_from("<I", mm, offs)[0]
        offs += 4
        offs = _skip_gguf_value(mm, offs, v_type)

    target_bytes = target_tensor.encode('utf-8')
    target_rel_offset = None
    target_type = None
    target_shape = None

    for _ in range(tensor_count):
        name_len = struct.unpack_from("<Q", mm, offs)[0]
        offs += 8
        is_target = (name_len == len(target_bytes) and mm[offs:offs+name_len].tobytes() == target_bytes)
        offs += name_len

        n_dims = struct.unpack_from("<I", mm, offs)[0]
        offs += 4
        shape = struct.unpack_from(f"<{n_dims}Q", mm, offs)
        offs += 8 * n_dims
        t_type = struct.unpack_from("<I", mm, offs)[0]
        offs += 4
        rel_offset = struct.unpack_from("<Q", mm, offs)[0]
        offs += 8

        if is_target:
            target_shape = shape
            target_type = t_type
            target_rel_offset = rel_offset

    padding = offs % alignment
    if padding != 0:
        offs += (alignment - padding)
    data_offset = offs

    if target_shape is None:
        raise RuntimeError(f"Cannot find {target_tensor} in {model_path}")

    abs_offset = data_offset + target_rel_offset
    n_embd = target_shape[0]
    vocab_size = target_shape[1]

    qtype = GGMLQuantizationType(target_type)
    if qtype in GGML_QUANT_SIZES:
        block_size, type_size = GGML_QUANT_SIZES[qtype]
        bytes_per_row = (n_embd // block_size) * type_size
    elif qtype == GGMLQuantizationType.F32:
        bytes_per_row = n_embd * 4
    elif qtype == GGMLQuantizationType.F16:
        bytes_per_row = n_embd * 2
    else:
        raise ValueError(f"Unsupported quantization: {qtype.name}")

    total_bytes = vocab_size * bytes_per_row
    raw_data = mm[abs_offset: abs_offset + total_bytes]

    if qtype == GGMLQuantizationType.F32:
        raw_data = raw_data.view(np.float32).reshape(vocab_size, n_embd)
    elif qtype == GGMLQuantizationType.F16:
        raw_data = raw_data.view(np.float16).reshape(vocab_size, n_embd)
    else:
        raw_data = raw_data.reshape(vocab_size, bytes_per_row)

    elapsed = time.time() - t_start
    print(f"[llama] Loaded embedding table ({qtype.name}, {n_embd}d, {vocab_size} tokens) in {elapsed*1000:.0f}ms", flush=True)
    return LlamaEmbeddingTable(raw_data, qtype)


# Auto-initialize on import
init()
