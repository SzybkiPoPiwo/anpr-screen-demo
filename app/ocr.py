from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

import cv2
import numpy as np
import easyocr

# Prosta walidacja „PL-like”: 1–3 litery + 4–5 znaków alnum
PLATE_RE = re.compile(r"^[A-Z]{1,3}[A-Z0-9]{4,5}$")


def normalize_text(s: str) -> str:
    s = s.upper()
    return "".join(ch for ch in s if ch.isalnum())


def preprocess(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
    )
    return thr


@dataclass
class OcrResult:
    plate: Optional[str]
    confidence: float
    raw_candidates: List[Tuple[str, float]]


class PlateOcr:
    def __init__(self, use_preprocessing: bool = True, gpu: bool = False):
        # „en” wystarczy, bo tablice to A-Z i cyfry
        self.reader = easyocr.Reader(["en"], gpu=gpu)
        self.use_preprocessing = use_preprocessing

    def read_plate(self, img_bgr: np.ndarray) -> OcrResult:
        img = preprocess(img_bgr) if self.use_preprocessing else img_bgr
        results = self.reader.readtext(img)

        candidates: List[Tuple[str, float]] = []

        for (_bbox, text, conf) in results:
            t = normalize_text(text)

            if len(t) < 6 or len(t) > 8:
                continue
            if not t[0].isalpha():
                continue
            if sum(ch.isdigit() for ch in t) == 0:
                continue

            score = float(conf)
            if PLATE_RE.match(t):
                candidates.append((t, score))
            else:
                # dalej pokaż jako kandydata, ale „ukarany”
                candidates.append((t, score * 0.7))

        candidates.sort(key=lambda x: x[1], reverse=True)

        best = candidates[0] if candidates else (None, 0.0)
        plate = best[0] if best[0] else None
        best_conf = best[1] if best[0] else 0.0

        return OcrResult(plate=plate, confidence=best_conf, raw_candidates=candidates[:5])
