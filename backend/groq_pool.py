"""
groq_pool.py - Groq calls with automatic API-key rotation and fail-over.

Keys are read from the environment (any of these, all are merged):
    GROQ_API_KEYS   = key1,key2,key3,key4     (comma / semicolon / space / newline separated)
    GROQ_API_KEY    = key1                    (single key, or also a comma list)
    GROQ_API_KEY_1 .. GROQ_API_KEY_10

Behaviour:
  * Round-robin: every call starts on the next key, so load (and per-minute
    token limits) is spread across all keys.
  * 429 / token-limit error  -> that key is put on cooldown (using Groq's own
    "try again in ..." hint when present) and the next key is tried at once.
  * 401/403 (dead key)       -> key is benched for 1 hour, next key is tried.
  * 5xx / timeout            -> next key is tried, no cooldown.
  * Anything else (bad request, bad prompt) -> raised immediately; it would
    fail on every key, so no keys are burned.
  * If every key is cooling down, the one that frees up first is still tried
    (the cooldown is only an estimate).
"""
import os
import re
import time
import threading
import logging

from langchain_groq import ChatGroq

logger = logging.getLogger("groq_pool")

_lock = threading.Lock()
_cooldown_until: dict = {}      # key -> epoch seconds when it may be used again
_rr_index = 0

AUTH_COOLDOWN_S = 3600
MIN_RATE_COOLDOWN_S = 5
DEFAULT_RATE_COOLDOWN_S = 60
MAX_COOLDOWN_S = 24 * 3600


def load_keys() -> list:
    blobs = [os.getenv("GROQ_API_KEYS") or "", os.getenv("GROQ_API_KEY") or ""]
    blobs += [os.getenv(f"GROQ_API_KEY_{i}") or "" for i in range(1, 11)]
    keys = []
    for blob in blobs:
        for k in re.split(r"[,;|\s]+", blob):
            k = k.strip().strip("\"'")
            if k and k not in keys:
                keys.append(k)
    return keys


def _mask(key: str) -> str:
    return f"{key[:4]}...{key[-4:]}" if len(key) > 10 else "****"


def _parse_wait_seconds(msg: str):
    """'Please try again in 1h2m3.5s' / '7m12s' / '340ms' -> seconds (float) or None."""
    m = re.search(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s)\s*)+)", msg, re.I)
    if not m:
        return None
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", m.group(1), re.I):
        n, u = float(num), unit.lower()
        total += n * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[u]
    return total or None


def _classify(e: Exception) -> str:
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    msg = str(e).lower()
    if status == 429 or any(s in msg for s in ("rate limit", "rate_limit", "tokens per", "requests per", "quota")):
        return "rate"
    if status in (401, 403) or any(s in msg for s in ("invalid api key", "invalid_api_key", "api_key client option")):
        return "auth"
    if (isinstance(status, int) and status >= 500) or any(
        s in msg for s in ("overloaded", "timeout", "timed out", "connection error", "temporarily", "service unavailable")
    ):
        return "transient"
    return "fatal"


def _ordered_keys(keys: list):
    global _rr_index
    now = time.time()
    with _lock:
        start = _rr_index % len(keys)
        _rr_index += 1
        rotated = keys[start:] + keys[:start]
        ready = [k for k in rotated if _cooldown_until.get(k, 0) <= now]
        cooling = sorted((k for k in rotated if _cooldown_until.get(k, 0) > now),
                         key=lambda k: _cooldown_until[k])
    return ready + cooling


def _bench(key: str, seconds: float):
    seconds = max(0.0, min(seconds, MAX_COOLDOWN_S))
    with _lock:
        _cooldown_until[key] = time.time() + seconds


def groq_invoke(prompt, *, model="openai/gpt-oss-120b", temperature=0.0,
                max_tokens=None, json_mode=False):
    """Drop-in replacement for ChatGroq(...).invoke(prompt) with key fail-over."""
    keys = load_keys()
    if not keys:
        raise RuntimeError(
            "No Groq API key is configured on this server. "
            "Set GROQ_API_KEYS (comma-separated) or GROQ_API_KEY in the host's environment."
        )

    last_err = None
    for key in _ordered_keys(keys):
        kwargs = dict(model=model, temperature=temperature, groq_api_key=key,
                      max_retries=0, timeout=60)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        try:
            return ChatGroq(**kwargs).invoke(prompt)
        except Exception as e:
            last_err = e
            kind = _classify(e)
            if kind == "rate":
                wait = _parse_wait_seconds(str(e)) or DEFAULT_RATE_COOLDOWN_S
                _bench(key, max(wait, MIN_RATE_COOLDOWN_S))
                logger.warning(f"Groq key {_mask(key)} rate-limited, cooling {int(wait)}s - trying next key.")
            elif kind == "auth":
                _bench(key, AUTH_COOLDOWN_S)
                logger.error(f"Groq key {_mask(key)} rejected (invalid/revoked) - benched 1h, trying next key.")
            elif kind == "transient":
                logger.warning(f"Groq transient error on key {_mask(key)}: {str(e)[:120]} - trying next key.")
            else:
                raise

    raise RuntimeError(f"All {len(keys)} Groq key(s) failed. Last error: {str(last_err)[:300]}")


def pool_status() -> dict:
    """Safe to expose: counts only, never key material."""
    keys = load_keys()
    now = time.time()
    with _lock:
        waits = [_cooldown_until.get(k, 0) - now for k in keys]
    cooling = [w for w in waits if w > 0]
    return {
        "total_keys": len(keys),
        "available_now": len(keys) - len(cooling),
        "cooling": len(cooling),
        "soonest_retry_s": int(min(cooling)) if cooling else 0,
    }