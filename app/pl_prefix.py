from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "prefix_map_pl.json"


def _clean_plate(s: str) -> str:
    return (s or "").upper().replace(" ", "").strip()


@lru_cache(maxsize=1)
def _load() -> dict:
    if not DATA_PATH.exists():
        return {"voivodeship_by_first_letter": {}, "known_prefixes_optional": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def region_for_plate(plate: Optional[str]) -> Optional[str]:
    p = _clean_plate(plate or "")
    if not p:
        return None

    data = _load()
    known = data.get("known_prefixes_optional", {}) or {}
    voiv1 = data.get("voivodeship_by_first_letter", {}) or {}

    # 3 znaki (np. ERA)
    if len(p) >= 3 and p[:3] in known:
        return known[p[:3]]

    # 2 znaki (np. KR, WA)
    if len(p) >= 2 and p[:2] in known:
        return known[p[:2]]

    # fallback: 1 litera województwa (np. E -> łódzkie)
    return voiv1.get(p[0])
