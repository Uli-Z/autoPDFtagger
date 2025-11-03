import os
import json
import logging
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional, Tuple
from autoPDFtagger.config import config as app_config
from autoPDFtagger import cache
import hashlib

# LiteLLM is optional at import time for tests; we stub usage when patched
try:
    import litellm  # type: ignore
    from litellm import completion  # type: ignore
    # Keep LiteLLM's own logger quiet at INFO to avoid breaking our status board
    try:
        logging.getLogger("litellm").setLevel(logging.WARNING)
    except Exception:
        pass
except Exception:  # pragma: no cover - tests will monkeypatch call sites
    litellm = None  # type: ignore
    completion = None  # type: ignore


# Very small price map; values are $ per 1k tokens as (input, output)
# Unknown models default to 0 cost.
_PRICE_MAP: Dict[str, Tuple[float, float]] = {
    # OpenAI common
    "openai/gpt-4o": (0.005, 0.015),
    "openai/gpt-4o-mini": (0.0005, 0.0015),
    "openai/gpt-3.5-turbo-1106": (0.001, 0.002),
    # Common dated aliases mapped to the nearest known rate
    "openai/gpt-4o-2024-08-06": (0.005, 0.015),
    "openai/gpt-4o-mini-2024-07-18": (0.0005, 0.0015),
}


def infer_provider(model: str) -> Dict[str, str]:
    name = model.lower()
    if name.startswith("openai/") or name.startswith("gpt-") or name.startswith("gpt4o"):
        return {"provider": "openai", "family": "openai"}
    if name.startswith("gemini/") or name.startswith("google/") or name.startswith("gemini-"):
        return {"provider": "gemini", "family": "google"}
    if name.startswith("ollama/"):
        return {"provider": "ollama", "family": "local"}
    return {"provider": "unknown", "family": "unknown"}


def _compute_cost(model: str, usage: Dict[str, Any]) -> float:
    def _lookup(name: str) -> Optional[Tuple[float, float]]:
        return _PRICE_MAP.get(name)

    # Prefer config-defined rates if available
    rates = _rates_from_config(model)
    if not rates:
        rates = _lookup(model)
    if not rates:
        info = infer_provider(model)
        base = model.split('/')[-1].lower()
        # direct provider/key lookup
        rates = _lookup(f"{info['provider']}/{base}")
        if not rates and info["provider"] == "openai":
            # Fuzzy mapping for common OpenAI variants with date suffixes
            if "gpt-4o-mini" in base:
                rates = _lookup("openai/gpt-4o-mini")
            elif "gpt-4o" in base:
                rates = _lookup("openai/gpt-4o")
            elif "gpt-3.5-turbo" in base:
                # map generic 3.5-turbo to a known 3.5 spec
                rates = _lookup("openai/gpt-3.5-turbo-1106")
    if not rates:
        logging.debug("Cost estimation: unknown rates for model '%s' (usage=%s)", model, usage)
        return 0.0
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    return prompt * rates[0] / 1000.0 + completion_tokens * rates[1] / 1000.0


def _litellm_cost(resp: Any) -> Optional[float]:
    """Try to compute cost using LiteLLM's built-in helpers when available.

    Returns a float when successful, or None to indicate fallback should be used.
    """
    try:
        if litellm is None:
            return None
        # Newer LiteLLM versions expose completion_cost(response)
        fn = getattr(litellm, "completion_cost", None)
        if callable(fn):
            return float(fn(resp))
        # Try a few common historical helper names for compatibility
        for name in ("calculate_cost", "response_cost", "cost_per_response"):
            helper = getattr(litellm, name, None)
            if callable(helper):
                try:
                    return float(helper(resp))
                except Exception:
                    continue
    except Exception:
        return None
    return None


def _ensure_env_for_provider(model: str) -> None:
    prov = infer_provider(model)["provider"]
    if prov == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            # Fallback to config file if available
            key = None
            try:
                key = app_config.get("OPENAI-API", "API-Key", fallback=None)
                if not key:
                    key = app_config.get("OPENAI", "api_key", fallback=None)
            except Exception:
                key = None
            if key:
                os.environ["OPENAI_API_KEY"] = key
            else:
                raise RuntimeError("Missing OPENAI_API_KEY in environment for model: %s" % model)
    elif prov == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            key = None
            try:
                key = app_config.get("GEMINI-API", "API-Key", fallback=None)
                if not key:
                    key = app_config.get("GEMINI", "api_key", fallback=None)
            except Exception:
                key = None
            if key:
                os.environ["GEMINI_API_KEY"] = key
            else:
                raise RuntimeError("Missing GEMINI_API_KEY in environment for model: %s" % model)
    elif prov == "ollama":
        # no key required
        pass


def run_chat(
    model: str,
    messages: List[Dict[str, Any]],
    json_mode: bool = False,
    schema: Optional[Dict[str, Any]] = None,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Run a chat completion via LiteLLM.

    Returns (text, usage) where usage optionally includes a computed 'cost'.
    """
    if completion is None:
        raise RuntimeError("litellm not installed; cannot call run_chat without monkeypatching.")

    _ensure_env_for_provider(model)

    # Cache lookup
    try:
        norm_messages: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            norm_messages.append({"role": role, "content": content})
        key_obj = {
            "v": 1,
            "type": "chat",
            "model": model,
            "json_mode": bool(json_mode),
            "has_schema": bool(schema),
            "temperature": float(temperature) if temperature is not None else None,
            "max_tokens": int(max_tokens) if max_tokens is not None else None,
            "messages": norm_messages,
        }
        key_str = json.dumps(key_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        key = hashlib.sha256(key_str.encode("utf-8")).hexdigest()
        cached = cache.get("chat", key)
        if cached and isinstance(cached, dict) and "text" in cached:
            logging.info("Chat cache hit (model=%s)", model)
            prev_usage = dict(cached.get("usage") or {})
            saved = float(prev_usage.get("cost", 0.0) or 0.0)
            usage = {"cost": 0.0, "saved_cost": saved, "cache_hit": True}
            return str(cached.get("text") or ""), usage
    except Exception:
        pass

    effective_temperature = float(temperature)
    model_name = model.lower()
    if "gpt-5" in model_name and abs(effective_temperature - 1.0) > 1e-6:
        logging.debug(
            "Clamping temperature to 1.0 for model '%s' (requested %.3f)",
            model,
            effective_temperature,
        )
        effective_temperature = 1.0

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": effective_temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if schema:
        # LiteLLM accepts 'functions'/'tool_choice' or 'response_format' depending on model; keep simple
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    logging.debug("LLM chat request: %s", {k: v for k, v in kwargs.items() if k != "messages"})
    # Some providers/versions print to stdout/stderr; capture to keep progress bars clean
    _buf_out, _buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(_buf_out), redirect_stderr(_buf_err):
        resp = completion(**kwargs)  # type: ignore[arg-type]
    _out_text = _buf_out.getvalue().strip()
    _err_text = _buf_err.getvalue().strip()
    if _out_text:
        logging.debug("LiteLLM stdout: %s", _out_text)
    if _err_text:
        logging.debug("LiteLLM stderr: %s", _err_text)
    try:
        text = resp["choices"][0]["message"]["content"]
    except Exception:
        # Some providers return objects; try attribute access
        text = getattr(resp.choices[0].message, "content", "")
    usage = {}
    raw_usage = getattr(resp, "usage", None) or resp.get("usage", {})
    if raw_usage:
        try:
            usage = {
                "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                "completion_tokens": raw_usage.get("completion_tokens", 0),
                "total_tokens": raw_usage.get("total_tokens", 0),
            }
        except Exception:
            # best-effort
            usage = {k: raw_usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in raw_usage}
    # cost estimation: prefer LiteLLM helper if available
    cost = _litellm_cost(resp)
    if cost is None:
        cost = _compute_cost(model, usage)
    usage["cost"] = cost
    usage["saved_cost"] = 0.0
    usage["cache_hit"] = False
    try:
        cache.set("chat", key, {"text": text or "", "usage": usage})
    except Exception:
        pass
    return text or "", usage


def run_vision(
    model: str,
    prompt: str,
    images_b64: List[str],
    temperature: float = 0.8,
    max_tokens: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Run a vision-capable chat with image inputs. Raises RuntimeError if unsupported.
    """
    if not images_b64:
        return "", {"cost": 0.0}

    if completion is None:
        raise RuntimeError("litellm not installed; cannot call run_vision without monkeypatching.")

    _ensure_env_for_provider(model)

    # Cache lookup based on prompt + image hashes
    try:
        image_hashes = [hashlib.sha256((b64 or "").encode("utf-8")).hexdigest() for b64 in images_b64]
        key_obj = {
            "v": 1,
            "type": "vision",
            "model": model,
            "temperature": float(temperature) if temperature is not None else None,
            "max_tokens": int(max_tokens) if max_tokens is not None else None,
            "prompt": prompt,
            "images": image_hashes,
        }
        key_str = json.dumps(key_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        key = hashlib.sha256(key_str.encode("utf-8")).hexdigest()
        cached = cache.get("vision", key)
        if cached and isinstance(cached, dict) and "text" in cached:
            logging.info("Vision cache hit (model=%s, images=%d)", model, len(images_b64))
            prev_usage = dict(cached.get("usage") or {})
            saved = float(prev_usage.get("cost", 0.0) or 0.0)
            usage = {"cost": 0.0, "saved_cost": saved, "cache_hit": True}
            return str(cached.get("text") or ""), usage
    except Exception:
        pass

    # Construct OpenAI-style content parts
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    logging.debug("LLM vision request: %s (images=%d)", {k: v for k, v in kwargs.items() if k != "messages"}, len(images_b64))
    # Capture any provider prints to keep our board intact
    _buf_out, _buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(_buf_out), redirect_stderr(_buf_err):
        resp = completion(**kwargs)  # type: ignore[arg-type]
    _out_text = _buf_out.getvalue().strip()
    _err_text = _buf_err.getvalue().strip()
    if _out_text:
        logging.debug("LiteLLM stdout: %s", _out_text)
    if _err_text:
        logging.debug("LiteLLM stderr: %s", _err_text)
    try:
        text = resp["choices"][0]["message"]["content"]
    except Exception:
        text = getattr(resp.choices[0].message, "content", "")
    usage = {}
    raw_usage = getattr(resp, "usage", None) or resp.get("usage", {})
    if raw_usage:
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens", 0),
            "completion_tokens": raw_usage.get("completion_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }
    cost = _litellm_cost(resp)
    if cost is None:
        cost = _compute_cost(model, usage)
    usage["cost"] = cost
    usage["saved_cost"] = 0.0
    usage["cache_hit"] = False
    try:
        cache.set("vision", key, {"text": text or "", "usage": usage})
    except Exception:
        pass
    return text or "", usage
def _rates_from_config(model: str) -> Optional[Tuple[float, float]]:
    """Try to read pricing from config [PRICING] section.

    Expected keys (any one variant):
      - "{model}.input_per_1k" and "{model}.output_per_1k" (exact model string)
      - "{provider}/{base}.input_per_1k" and "{provider}/{base}.output_per_1k"
    Returns (input_rate, output_rate) in $/1k tokens, or None if not present.
    """
    try:
        if not app_config.has_section("PRICING"):
            return None
    except Exception:
        return None

    def _get_pair(prefix: str) -> Optional[Tuple[float, float]]:
        try:
            i = app_config.get("PRICING", f"{prefix}.input_per_1k", fallback=None)
            o = app_config.get("PRICING", f"{prefix}.output_per_1k", fallback=None)
            if i is None or o is None:
                return None
            return float(i), float(o)
        except Exception:
            return None

    # 1) Exact model key
    rates = _get_pair(model)
    if rates:
        return rates

    # 2) Provider + base name
    info = infer_provider(model)
    base = model.split('/')[-1]
    rates = _get_pair(f"{info['provider']}/{base}")
    if rates:
        return rates
    return None
