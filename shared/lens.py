"""
Neutral client layer for INFERENCE-TIME white-box access to a vLLM server running the `vllm-lens`
plugin (UKGovernmentBEIS/vllm-lens). Used by blue's white-box tools (`blue_team/wb_tools.py`) and
usable by green for checks. Imports NO team package.

Why a separate client instead of `vllm_lens.client`: the blue host must not need vllm/torch to talk to
the server. This module speaks the plugin's HTTP wire format directly (numpy + zstandard + cloudpickle
+ stdlib): `vllm_xargs.output_residual_stream` (capture), `vllm_xargs.apply_steering_vectors`
(steer), `vllm_xargs.apply_hooks` (fixed hooks). Verified against vllm-lens 1.2.1 on 2026-08-17.

Wire facts (verified):
  * activations come back as response["activations"]["residual_stream"] = tensor-dict
    {data: b64(zstd(bytes)), dtype, original_dtype, shape:[n_layers_requested, n_positions, d_model]};
    positions = prompt tokens + generated tokens (all positions of the request); layers stacked in the
    order requested. Invalid layer indices are SILENTLY ignored (no `activations` key) — hence
    `probe_n_layers()`.
  * hooks: {"fn": {"cloudpickle": b64}, "layer_indices": [...], "pre": bool}; `fn(ctx, h)` runs on the
    server -> ARBITRARY CODE EXECUTION. Only the FIXED hook factories below are ever shipped; they are
    closures (pickled by value) that use torch only. Results: response["hook_results"][hook_idx][key].
  * steering: {"activations": tensor-dict (n_layers, d) or (n_layers, n_pos, d), "layer_indices",
    "scale", "norm_match", "position_indices"}.
  * The plugin forces enforce_eager on the server (~30 tok/s per request on our pods).

Safety posture for the auditing game: this module never returns raw hidden states to an agent-facing
surface — callers persist them (`save_acts`) and hand out ids/summaries. Steering scale and noise
sigma are capped here (`MAX_STEER_SCALE`, `MAX_NOISE_SIGMA`).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import numpy as np

try:  # zstandard is what the plugin uses; without it we can still send uncompressed vectors
    import zstandard as _zstd
except Exception:  # pragma: no cover
    _zstd = None
try:
    import cloudpickle as _cp
except Exception:  # pragma: no cover
    _cp = None

MAX_STEER_SCALE = 1.5   # norm-matched PER TOKEN (h_i + scale*|h_i|*v_hat): 0.25 usually coherent, 0.5 usually not
MAX_NOISE_SIGMA = 2.0   # relative to the per-token residual norm (1.0 = noise as large as the signal)
_TIMEOUT = 900


# ── tensor codec ────────────────────────────────────────────────────────────────────────────────
def decode_tensor(d: dict) -> np.ndarray:
    """vllm-lens tensor-dict -> float32 numpy (bf16/f16 upcast)."""
    raw = base64.b64decode(d["data"])
    if d.get("compression") == "zstd":
        if _zstd is None:
            raise RuntimeError("zstandard is required to decode compressed activations")
        raw = _zstd.ZstdDecompressor().decompress(raw)
    arr = np.frombuffer(raw, dtype=np.dtype(d["dtype"])).reshape(d["shape"])
    if d.get("original_dtype") == "torch.bfloat16":
        arr = (arr.astype(np.int32) << 16).view(np.float32)
    elif arr.dtype != np.float32:
        arr = arr.astype(np.float32)
    return arr


def encode_tensor(arr: np.ndarray) -> dict:
    """numpy -> vllm-lens tensor-dict (float32; zstd if available)."""
    arr = np.ascontiguousarray(np.asarray(arr, dtype=np.float32))
    raw = arr.tobytes()
    out = {"dtype": "float32", "original_dtype": "torch.float32", "shape": list(arr.shape)}
    if _zstd is not None:
        out["data"] = base64.b64encode(_zstd.ZstdCompressor(level=1).compress(raw)).decode("ascii")
        out["compression"] = "zstd"
    else:
        out["data"] = base64.b64encode(raw).decode("ascii")
    return out


def _decode_hook_value(v):
    if isinstance(v, dict) and v.get("__type__") == "tensor":
        return decode_tensor(v)
    if isinstance(v, dict) and v.get("__type__") == "cloudpickle":
        return "<opaque>"          # never unpickle server payloads on the client
    return v


# ── fixed hook factories (the ONLY hooks ever shipped) ─────────────────────────────────────────
# Closures pickled BY VALUE (cloudpickle); bodies use torch only; deterministic across TP ranks.
def make_logit_lens_hook(top_k: int, positions: list[int] | None):
    """Per hooked layer: final-norm + unembed the residual at `positions` (None = last position);
    saves top-k token ids + probs under key f"L{layer}". Matmul in the weight's dtype (no fp32 copy)."""
    top_k = int(max(1, min(top_k, 20)))
    pos = None if positions is None else [int(p) for p in positions]

    def hook(ctx, h):
        import torch
        W = ctx.get_parameter("lm_head.weight")
        try:
            g = ctx.get_parameter("model.norm.weight")
        except Exception:
            g = None
        idx = [h.shape[0] - 1] if pos is None else [p if p >= 0 else h.shape[0] + p for p in pos]
        idx = [i for i in idx if 0 <= i < h.shape[0]]
        x = h[idx].float()
        if g is not None:
            x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + 1e-6) * g.float()
        logits = (x.to(W.dtype) @ W.T).float()
        p = torch.softmax(logits, -1)
        top = p.topk(top_k, dim=-1)
        ctx.saved[f"L{ctx.layer_idx}"] = {"positions": idx, "ids": top.indices.tolist(),
                                          "probs": [[round(v, 5) for v in row] for row in top.values.tolist()]}
        return None
    return hook


def make_noise_prehook(sigma: float, seed: int):
    """Add Gaussian noise to the layer INPUT (pre-hook), seeded per layer (rank-deterministic).

    `sigma` is RELATIVE: per token, the noise vector's expected norm = sigma x that token's residual
    norm (per-dim std = sigma x the token's RMS activation). So sigma=1 is a perturbation as large as the
    signal itself; 0.05-0.3 is the "moderate" band worth sweeping; > ~1 is gibberish territory.
    """
    sigma = float(min(max(sigma, 0.0), MAX_NOISE_SIGMA))
    seed = int(seed)

    def hook(ctx, h):
        import torch
        if sigma <= 0:
            return None
        g = torch.Generator(device=h.device)
        g.manual_seed(seed * 1000003 + ctx.layer_idx)
        rms = h.float().pow(2).mean(-1, keepdim=True).sqrt().to(h.dtype)          # (..., 1) per token
        return h + sigma * rms * torch.randn(h.shape, generator=g, device=h.device, dtype=h.dtype)
    return hook


def make_patch_hook(donor: np.ndarray, positions: list[int] | None):
    """Overwrite hidden states at `positions` (None = last) with `donor` rows (shape (n_pos, d))."""
    donor = np.ascontiguousarray(np.asarray(donor, dtype=np.float32))
    pos = None if positions is None else [int(p) for p in positions]

    def hook(ctx, h):
        import torch
        d = torch.as_tensor(donor, device=h.device, dtype=h.dtype)
        idx = [h.shape[0] - 1] if pos is None else [p if p >= 0 else h.shape[0] + p for p in pos]
        h = h.clone()
        for k, i in enumerate(idx):
            if 0 <= i < h.shape[0] and k < d.shape[0]:
                h[i] = d[k]
        return h
    return hook


def hook_wire(fn, layer_indices: list[int], pre: bool = False) -> dict:
    if _cp is None:
        raise RuntimeError("cloudpickle is required to ship hooks")
    return {"fn": {"cloudpickle": base64.b64encode(_cp.dumps(fn)).decode("ascii")},
            "layer_indices": [int(i) for i in layer_indices], "pre": bool(pre)}


def steering_wire(vec: np.ndarray, layer_indices: list[int], scale: float, norm_match: bool = True,
                  position_indices: list[int] | None = None) -> dict:
    """vec: (d,) broadcast to all layers, or (n_layers, d), or (n_layers, n_pos, d)."""
    v = np.asarray(vec, dtype=np.float32)
    if v.ndim == 1:
        v = np.tile(v[None, :], (len(layer_indices), 1))
    if v.shape[0] != len(layer_indices):
        raise ValueError(f"steering vector dim0 {v.shape[0]} != len(layer_indices) {len(layer_indices)}")
    scale = float(max(-MAX_STEER_SCALE, min(MAX_STEER_SCALE, scale)))
    return {"activations": encode_tensor(v), "layer_indices": [int(i) for i in layer_indices],
            "scale": scale, "norm_match": bool(norm_match), "position_indices": position_indices}


# ── the client ─────────────────────────────────────────────────────────────────────────────────
@dataclass
class LensOutput:
    text: str
    reasoning: str | None
    activations: np.ndarray | None          # (n_layers_requested, n_positions, d_model) float32
    layers: list[int]                       # layers actually captured (in order)
    n_prompt_tokens: int | None
    hook_results: dict                      # {hook_idx: {key: value}}
    finish_reason: str | None
    usage: dict
    seconds: float
    error: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


class LensClient:
    """Chat-completions client to a vllm-lens server. `served_name` selects base or LoRA."""

    def __init__(self, base_url: str, served_name: str, api_key: str = "EMPTY", timeout: float = _TIMEOUT):
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.served_name = served_name
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read()[:400].decode(errors='replace')}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}

    def chat(self, messages: list[dict], *, max_tokens: int = 1, temperature: float = 0.0,
             seed: int | None = None, thinking: bool = False, prefix: str | None = None,
             capture_layers: list[int] | None = None, steering: list[dict] | None = None,
             hooks: list[dict] | None = None, extra_body: dict | None = None) -> LensOutput:
        body = {"model": self.served_name, "messages": list(messages), "max_tokens": int(max_tokens),
                "temperature": float(temperature)}
        if seed is not None:
            body["seed"] = int(seed)
        if not thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        if prefix:
            body["messages"] = list(messages) + [{"role": "assistant", "content": prefix}]
            body["continue_final_message"] = True
            body["add_generation_prompt"] = False
        xargs = {}
        if capture_layers:
            xargs["output_residual_stream"] = json.dumps([int(i) for i in capture_layers])
        if steering:
            xargs["apply_steering_vectors"] = json.dumps(steering)
        if hooks:
            xargs["apply_hooks"] = json.dumps(hooks)
        if xargs:
            body["vllm_xargs"] = xargs
        if extra_body:
            body.update(extra_body)
        t0 = time.time()
        r = self._post("/v1/chat/completions", body)
        dt = time.time() - t0
        if "error" in r:
            return LensOutput("", None, None, [], None, {}, None, {}, dt, error=str(r["error"]), raw=r)
        ch = (r.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        acts = None
        layers = []
        a = (r.get("activations") or {}).get("residual_stream")
        if a is not None:
            acts = decode_tensor(a)
            layers = [int(i) for i in (capture_layers or [])][:acts.shape[0]]
        hr = {k: {kk: _decode_hook_value(vv) for kk, vv in v.items()} for k, v in (r.get("hook_results") or {}).items()}
        return LensOutput(text=msg.get("content") or "", reasoning=msg.get("reasoning") or msg.get("reasoning_content"),
                          activations=acts, layers=layers,
                          n_prompt_tokens=(r.get("usage") or {}).get("prompt_tokens"),
                          hook_results=hr, finish_reason=ch.get("finish_reason"), usage=r.get("usage") or {},
                          seconds=dt, raw=r)

    async def achat(self, *a, **kw) -> LensOutput:
        return await asyncio.to_thread(self.chat, *a, **kw)

    def probe_n_layers(self, lo: int = 8, hi: int = 128) -> int | None:
        """Number of decoder layers, found by probing capture (invalid layers are silently ignored)."""
        def ok(L):
            o = self.chat([{"role": "user", "content": "hi"}], max_tokens=1, capture_layers=[L])
            return o.activations is not None
        if not ok(0):
            return None
        a, b = 0, hi                       # ok(a) True, ok(b) False (assume)
        if ok(b):
            return b + 1
        while b - a > 1:
            m = (a + b) // 2
            if ok(m):
                a = m
            else:
                b = m
        return a + 1

    def d_model(self) -> int | None:
        o = self.chat([{"role": "user", "content": "hi"}], max_tokens=1, capture_layers=[0])
        return None if o.activations is None else int(o.activations.shape[-1])


# ── activation persistence + small linear-algebra helpers (numpy only) ────────────────────────
def save_acts(path: str, acts: np.ndarray, meta: dict) -> None:
    """Persist as fp16 .npy + sidecar .json (positions, layers, ...)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.save(path, np.asarray(acts, dtype=np.float16))
    with open(path + ".json", "w") as f:
        json.dump(meta, f)


def load_acts(path: str) -> tuple[np.ndarray, dict]:
    arr = np.load(path).astype(np.float32)
    try:
        meta = json.load(open(path + ".json"))
    except Exception:
        meta = {}
    return arr, meta


def select_positions(acts: np.ndarray, positions) -> np.ndarray:
    """acts (n_layers, n_pos, d) -> (n_layers, k, d) for positions 'last' | 'mean' | 'all' | [idx]."""
    if positions in (None, "last"):
        return acts[:, -1:, :]
    if positions == "mean":
        return acts.mean(axis=1, keepdims=True)
    if positions == "all":
        return acts
    idx = [p if p >= 0 else acts.shape[1] + p for p in positions]
    idx = [i for i in idx if 0 <= i < acts.shape[1]]
    return acts[:, idx, :]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64).ravel(); b = b.astype(np.float64).ravel()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float = 0.1, iters: int = 300) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Per-dimension-standardised, L2-regularised logistic regression by gradient descent (numpy only).
    d >> n is the normal regime here (d_model ~4-5k, tens of rows). l2=0.1 (penalty l2*w) was chosen
    empirically: it keeps the probe a direction that TRANSFERS across items and handles (AUC 1.0 on a
    different served model in the dev check) whereas weak regularisation memorises and stronger
    global-scale variants transfer worse. Returns (w, b, mu, sd) in the ORIGINAL feature space (apply
    as sigmoid(((x-mu)/sd) @ w + b)); the intercept may shift across handles — judge transfer by AUC."""
    X = np.asarray(X, dtype=np.float64); y = np.asarray(y, dtype=np.float64)
    mu = X.mean(0); sd = X.std(0) + 1e-6
    Z = (X - mu) / sd
    n, d = Z.shape
    w = np.zeros(d); b = 0.0; lr = 0.1
    for _ in range(iters):
        p = _sigmoid(Z @ w + b)
        g = Z.T @ (p - y) / n + l2 * w
        gb = float((p - y).mean())
        w -= lr * g; b -= lr * gb
    return w, b, mu, sd


def logreg_logits(X: np.ndarray, w: np.ndarray, b: float, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    Z = (np.asarray(X, dtype=np.float64) - mu) / sd
    return Z @ w + b


def logreg_scores(X: np.ndarray, w: np.ndarray, b: float, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return _sigmoid(logreg_logits(X, w, b, mu, sd))


def auc(scores: np.ndarray, y: np.ndarray) -> float | None:
    """ROC AUC via rank statistic (ties averaged)."""
    s = np.asarray(scores, dtype=np.float64); y = np.asarray(y).astype(int)
    n1, n0 = int(y.sum()), int((1 - y).sum())
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=np.float64)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[order[j + 1]] == s[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))
