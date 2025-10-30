import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from autoPDFtagger.config import config

ResponseTuple = Tuple[Optional[str], Dict[str, Any]]

_call_counts: Dict[Tuple[str, str], int] = defaultdict(int)


def reset() -> None:
    """Reset internal call counters (useful for tests and fresh CLI runs)."""
    _call_counts.clear()


def is_mock_model(model: str) -> bool:
    return bool(model) and model.startswith("TEST/")


def _candidate_paths(base: Path, task: str, index: int) -> Iterable[Path]:
    stem = base.stem
    if task:
        yield base.with_name(f"{stem}.{task}.{index}.json")
        if index == 0:
            yield base.with_name(f"{stem}.{task}.json")
    yield base.with_name(f"{stem}.json")


def fetch(doc, task: str, *, context: Optional[dict] = None) -> ResponseTuple:
    """
    Load a mock response for the given document/task combination.
    Returns (response_text, usage_dict). Falls back to (None, {"cost": 0.0}) if not found.
    """
    path = Path(doc.get_absolute_path())
    key = (str(path), task)
    index = _call_counts[key]
    _call_counts[key] += 1
    candidates = list(_candidate_paths(path, task, index))

    # Optional artificial latency for testing UI/concurrency (ms)
    try:
        latency_ms = int(config.get("AI", "test_mock_sleep_ms", fallback="0") or 0)
    except Exception:
        latency_ms = 0
    if latency_ms > 0:
        time.sleep(latency_ms / 1000.0)

    for candidate in candidates:
        if candidate.exists():
            try:
                with candidate.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception as exc:
                logging.warning("Failed to load mock response '%s': %s", candidate, exc)
                break

            response = payload.get("response", payload)
            usage = payload.get("usage", {"cost": 0.0})
            metadata = payload.get("meta") or {}
            if context:
                expected = metadata.get("expected")
                if expected is not None and expected != context:
                    logging.info(
                        "Mock metadata mismatch for %s (%s): expected %s, got %s",
                        candidate,
                        task,
                        expected,
                        context,
                    )

            if not isinstance(usage, dict):
                usage = {"cost": float(usage)}

            if isinstance(response, (dict, list)):
                response_text = json.dumps(response)
            elif response is None:
                response_text = None
            else:
                response_text = str(response)

            logging.debug(
                "Loaded mock response '%s' for %s (task=%s, call=%d).",
                candidate,
                path.name,
                task,
                index,
            )
            return response_text, usage

    logging.info(
        "Mock response not found for %s (task=%s, call=%d). Checked %s.",
        path.name,
        task,
        index,
        ", ".join(str(p) for p in candidates),
    )
    return None, {"cost": 0.0}
