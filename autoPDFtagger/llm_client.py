import os
import logging
from typing import Any, Dict, List, Optional, Tuple
from autoPDFtagger.config import config as app_config

# LiteLLM is optional at import time for tests; we stub usage when patched
try:
    from litellm import completion
except Exception:  # pragma: no cover - tests will monkeypatch call sites
    completion = None  # type: ignore


# Very small price map; values are $ per 1k tokens as (input, output)
# Unknown models default to 0 cost.
_PRICE_MAP: Dict[str, Tuple[float, float]] = {
    # OpenAI common
    "openai/gpt-4o": (0.005, 0.015),
    "openai/gpt-4o-mini": (0.0005, 0.0015),
    "openai/gpt-3.5-turbo-1106": (0.001, 0.002),
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
    rates = _PRICE_MAP.get(model)
    if not rates:
        # try by provider family
        info = infer_provider(model)
        key = f"{info['provider']}/{model.split('/')[-1]}"
        rates = _PRICE_MAP.get(key)
    if not rates:
        return 0.0
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    return prompt * rates[0] / 1000.0 + completion_tokens * rates[1] / 1000.0


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
    resp = completion(**kwargs)  # type: ignore[arg-type]
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
    # cost estimation
    usage["cost"] = _compute_cost(model, usage)
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
    resp = completion(**kwargs)  # type: ignore[arg-type]
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
    usage["cost"] = _compute_cost(model, usage)
    return text or "", usage
