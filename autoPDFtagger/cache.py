import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

_enabled: bool = True
_ttl_seconds: int = 24 * 60 * 60
_base_dir: Path = Path(os.path.expanduser("~/.autoPDFtagger/config"))


def configure(
    *,
    enabled: Optional[bool] = None,
    ttl_seconds: Optional[int] = None,
    base_dir: Optional[str] = None,
) -> None:
    global _enabled, _ttl_seconds, _base_dir
    if enabled is not None:
        _enabled = bool(enabled)
    if ttl_seconds is not None:
        try:
            _ttl_seconds = int(ttl_seconds)
        except Exception:
            pass
    if base_dir is not None and str(base_dir).strip():
        _base_dir = Path(os.path.expanduser(str(base_dir)))


def _bucket_dir(bucket: str) -> Path:
    d = _base_dir / bucket
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _path_for(bucket: str, key: str) -> Path:
    # shard by first two characters to avoid too many files in one folder
    shard = key[:2]
    folder = _bucket_dir(bucket) / shard
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return folder / f"{key}.json"


def get(bucket: str, key: str) -> Optional[dict]:
    if not _enabled:
        return None
    try:
        p = _path_for(bucket, key)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        # Check expiry
        now = time.time()
        exp = float(obj.get("expires_at", 0) or 0)
        created = float(obj.get("created_at", 0) or 0)
        # If no explicit expires_at, fall back to mtime + ttl
        if exp <= 0:
            try:
                mtime = p.stat().st_mtime
            except Exception:
                mtime = created or now
            exp = mtime + _ttl_seconds
        if now >= exp:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return obj.get("data")
    except Exception as e:
        logging.debug("Cache read error for %s/%s: %s", bucket, key[:8], e)
        return None


def set(bucket: str, key: str, data: dict) -> None:
    if not _enabled:
        return
    try:
        p = _path_for(bucket, key)
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
        try:
            payload = {
                "created_at": time.time(),
                "expires_at": time.time() + _ttl_seconds,
                "data": data,
            }
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, p)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logging.debug("Cache write error for %s/%s: %s", bucket, key[:8], e)

