import json
import logging


def tokenize_text(text: str) -> int:
    """Estimate token count for a string.
    Uses tiktoken (cl100k_base) when available, otherwise len(text)//4.
    Returns at least 1 when text is non-empty.
    """
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        try:
            return len(enc.encode(text or ""))
        except Exception:
            pass
    except Exception:
        pass
    return max(1, len(text or "") // 4)


def apply_text_budget(kind: str, filename: str, system_text: str, user_text: str, token_limit: int):
    """Apply a per-file token budget for a system+user text pair.

    - Preserves the system_text fully.
    - If intro alone exceeds the limit, log and return abort=True.
    - Otherwise, trims user_text proportionally to fit into the remaining budget and logs an INFO when trimming occurs.

    Returns a dict with:
      {
        'abort': bool,
        'reason': str|None,
        'user_text': str,
        'intro_tokens': int,
        'used_tokens': int,
      }
    """
    intro_tokens = tokenize_text(system_text)
    user_tokens = tokenize_text(user_text)
    if intro_tokens > token_limit:
        logging.info(
            f"[{kind} budget] %s: intro exceeds limit (intro≈%d > limit=%d); aborting request",
            filename, intro_tokens, token_limit,
        )
        return {
            'abort': True,
            'reason': 'intro_exceeds_limit',
            'user_text': user_text,
            'intro_tokens': intro_tokens,
            'used_tokens': intro_tokens,
        }
    total = intro_tokens + user_tokens
    if total > token_limit:
        budget = max(0, token_limit - intro_tokens)
        if user_tokens > 0 and budget < user_tokens:
            ratio = budget / max(1, user_tokens)
            cut = int(len(user_text) * ratio)
            user_text = user_text[: max(1, cut)]
        used = intro_tokens + tokenize_text(user_text)
        logging.info(
            f"[{kind} budget] %s: trimmed text to fit limit (used_tokens≈%d/%d)",
            filename, used, token_limit,
        )
        return {
            'abort': False,
            'reason': None,
            'user_text': user_text,
            'intro_tokens': intro_tokens,
            'used_tokens': used,
        }
    return {
        'abort': False,
        'reason': None,
        'user_text': user_text,
        'intro_tokens': intro_tokens,
        'used_tokens': total,
    }


def log_llm_request(kind: str, filename: str, parts: int, text_tokens: int, image_tokens: int | None, total_tokens: int, token_limit: int):
    """Standardize DEBUG log for LLM requests.
    If image_tokens is None, log a text-only variant.
    """
    if image_tokens is None:
        logging.debug(f"[{kind} request] tokens: total≈%d/%d", total_tokens, token_limit)
    else:
        logging.debug(
            f"[{kind} request] tokens: text≈%d, images≈%d, total≈%d/%d (parts=%d)",
            text_tokens, image_tokens, total_tokens, token_limit, parts,
        )


def json_guard(text: str) -> str:
    """Return a JSON object string extracted from model output.

    - If `text` is empty/None, return "{}".
    - If `text` is already valid JSON, return as-is.
    - Otherwise, try to slice the outermost {...} substring; fall back to "{}".
    """
    try:
        if not text:
            return "{}"
        json.loads(text)
        return text
    except Exception:
        try:
            s = str(text)
            start = s.find("{")
            end = s.rfind("}")
            if start != -1 and end != -1 and end > start:
                return s[start : end + 1]
        except Exception:
            pass
        return "{}"


def normalize_confidence_numbers(data, source: str | None = None):
    """Normalize confidence scales to 0..10 when models return 0..1.

    - If an object has only confidence values <= 1.0, scale all its *_confidence fields
      (and tags_confidence list) by 10 and round to nearest int, clamped to [0, 10].
    - Works for a dict or a list of dicts.
    """
    def _clamp(x: float) -> int:
        try:
            v = int(round(float(x) * 10.0))
            return max(0, min(10, v))
        except Exception:
            return 0

    def _process_obj(obj: dict) -> tuple[dict, bool]:
        vals: list[float] = []
        for k, v in obj.items():
            if k.endswith("_confidence") and isinstance(v, (int, float)):
                vals.append(float(v))
        tc = obj.get("tags_confidence")
        if isinstance(tc, list):
            for v in tc:
                if isinstance(v, (int, float)):
                    vals.append(float(v))
        if not vals:
            return obj, False
        if max(vals) <= 1.0:
            new_obj = dict(obj)
            for k, v in obj.items():
                if k.endswith("_confidence") and isinstance(v, (int, float)):
                    new_obj[k] = _clamp(float(v))
            if isinstance(tc, list):
                new_obj["tags_confidence"] = [
                    _clamp(float(v)) if isinstance(v, (int, float)) else v for v in tc
                ]
            return new_obj, True
        return obj, False

    try:
        if isinstance(data, dict):
            obj, changed = _process_obj(data)
            if changed:
                logging.info("[confidence normalize] source=%s scaled 0..1 → 0..10", source or "unknown")
            return obj
        if isinstance(data, list):
            changed_any = False
            out: list = []
            for x in data:
                if isinstance(x, dict):
                    nx, changed = _process_obj(x)
                    changed_any = changed_any or changed
                    out.append(nx)
                else:
                    out.append(x)
            if changed_any:
                logging.info("[confidence normalize] source=%s scaled 0..1 → 0..10 (array)", source or "unknown")
            return out
    except Exception:
        pass
    return data

