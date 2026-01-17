from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any

# ROOT/data/plates_db.json (bo db.py jest w ROOT/app/db.py)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PLATES_DB_PATH = DATA_DIR / "plates_db.json"

# prosty cache (szybko + działa w wątku OCR)
_db_cache: Dict[str, Dict[str, str]] | None = None
_db_mtime: float | None = None


def _clean_plate(s: str) -> str:
    return (s or "").upper().replace(" ", "").strip()


def _ensure_file_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not PLATES_DB_PATH.exists():
        PLATES_DB_PATH.write_text("{}", encoding="utf-8")


def _load_db() -> Dict[str, Dict[str, str]]:
    global _db_cache, _db_mtime

    _ensure_file_exists()
    mtime = PLATES_DB_PATH.stat().st_mtime

    # jeśli nie zmienił się plik, zwróć cache
    if _db_cache is not None and _db_mtime == mtime:
        return _db_cache

    try:
        raw = PLATES_DB_PATH.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    # normalizacja kluczy (tablic) – zawsze uppercase bez spacji
    normalized: Dict[str, Dict[str, str]] = {}
    for k, v in data.items():
        kk = _clean_plate(k)
        if not kk:
            continue
        if isinstance(v, dict):
            normalized[kk] = {
                "opis": str(v.get("opis", "") or ""),
                "tag": str(v.get("tag", "") or ""),
            }

    _db_cache = normalized
    _db_mtime = mtime
    return normalized


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomiczne na Windows


def _save_db(db: Dict[str, Dict[str, str]]) -> None:
    global _db_cache, _db_mtime
    _ensure_file_exists()

    _atomic_write_json(PLATES_DB_PATH, db)

    # odśwież cache po zapisie
    _db_cache = db
    _db_mtime = PLATES_DB_PATH.stat().st_mtime


def get_plate_info(plate: Optional[str]) -> Optional[dict]:
    p = _clean_plate(plate or "")
    if not p:
        return None
    db = _load_db()
    return db.get(p)


def upsert_plate(plate: str, opis: str, tag: str = "") -> None:
    p = _clean_plate(plate)
    if not p:
        return
    db = _load_db()
    db[p] = {"opis": (opis or "").strip(), "tag": (tag or "").strip()}
    _save_db(db)


def delete_plate(plate: str) -> bool:
    p = _clean_plate(plate)
    if not p:
        return False
    db = _load_db()
    existed = p in db
    if existed:
        db.pop(p, None)
        _save_db(db)
    return existed
