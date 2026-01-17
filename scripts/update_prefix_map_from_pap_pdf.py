from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import pdfplumber

# 1) Załącznik (często działa, ale czasem serwer zwraca coś innego niż PDF)
PAP_PDF_URL = "https://samorzad.pap.pl/sites/default/files/2024-01/wyr%C3%B3%C5%BCniki-powiaty.pdf"

# 2) Oficjalny PDF z ELI (bez captchy) – pełny Dz.U., ale zawiera Załącznik nr 13
ELI_DU_PDF_URL = "https://eli.gov.pl/api/acts/DU/2024/1709/text/O/D20241709.pdf"

OUT = Path(__file__).resolve().parent.parent / "data" / "prefix_map_pl.json"
TMP = Path(__file__).resolve().parent / "_src.pdf"
DBG = Path(__file__).resolve().parent / "_src_debug.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    # kluczowe: nie bierz brotli/gzip → ma być surowy PDF
    "Accept-Encoding": "identity",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
}

RX_LOWER_UPPER = re.compile(r"([a-ząćęłńóśźż])([A-Z])")
RX_UPPER_LOWER = re.compile(r"([A-Z]{1,3})([a-ząćęłńóśźż])")

RX_VOIV_HEADER = re.compile(r"^\s*\d+\s+([A-ZĄĆĘŁŃÓŚŹŻ\- ]+?)\s+([A-Z](?:\s*,\s*[A-Z])*)\s+")
RX_ENTRY = re.compile(
    r"(?P<name>[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\- ]+?)\s+"
    r"(?P<voiv>[A-Z])(?:\s*,\s*(?P<voiv2>[A-Z]))?\s+"
    r"(?P<codes>[A-Z0-9]{1,2}(?:\s*,\s*[A-Z0-9]{1,2})*)"
)


def is_pdf_bytes(b: bytes) -> bool:
    return b.startswith(b"%PDF-")


def fetch_bytes(url: str) -> bytes:
    s = requests.Session()
    r = s.get(url, headers=HEADERS, timeout=60)
    # jeśli coś jest nie tak, chcemy widzieć status/headers
    if r.status_code >= 400:
        raise requests.HTTPError(f"HTTP {r.status_code} dla {url}")
    return r.content


def download_any_pdf() -> bytes:
    last_err: Optional[Exception] = None

    for url in (PAP_PDF_URL, ELI_DU_PDF_URL):
        try:
            print("[INFO] Pobieram:", url)
            b = fetch_bytes(url)

            if not is_pdf_bytes(b):
                # zapisz debug (najczęściej HTML albo coś skompresowanego)
                head = b[:400]
                try:
                    txt = head.decode("utf-8", errors="replace")
                except Exception:
                    txt = repr(head)
                DBG.write_text(
                    f"URL: {url}\n"
                    f"FIRST_400_BYTES_AS_TEXT:\n{txt}\n",
                    encoding="utf-8",
                )
                raise ValueError(f"Pobrano coś, co nie wygląda jak PDF (brak %PDF-). Debug: {DBG}")

            print("[OK] Wygląda jak PDF (%PDF-).")
            return b

        except Exception as e:
            print("[WARN] Nie udało się pobrać poprawnego PDF z tego źródła:", e)
            last_err = e

    raise RuntimeError(f"Nie udało się pobrać PDF z żadnego źródła. Ostatni błąd: {last_err}")


def norm_line(s: str) -> str:
    s = s.replace("\u00a0", " ").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip()

    s = RX_LOWER_UPPER.sub(r"\1 \2", s)
    s = RX_UPPER_LOWER.sub(r"\1 \2", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def pl_lower_name(voiv_upper: str) -> str:
    return voiv_upper.strip().lower().replace("  ", " ")


def main():
    pdf_bytes = download_any_pdf()
    TMP.write_bytes(pdf_bytes)
    print("[OK] Zapisano PDF do:", TMP)

    voivodeship_by_first_letter: dict[str, str] = {}
    known_prefixes_optional: dict[str, str] = {}

    current_voiv_name: str | None = None
    current_voiv_letters: list[str] = []

    with pdfplumber.open(str(TMP)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            raw_lines = [ln for ln in text.splitlines() if ln.strip()]

            # sklejanie przerwań myślnikiem
            lines: list[str] = []
            i = 0
            while i < len(raw_lines):
                ln = raw_lines[i].strip()
                if ln.endswith("-") and i + 1 < len(raw_lines):
                    ln = ln + raw_lines[i + 1].strip()
                    i += 2
                else:
                    i += 1
                lines.append(ln)

            for ln in lines:
                ln = norm_line(ln)

                # nagłówek województwa
                m = RX_VOIV_HEADER.match(ln)
                if m:
                    voiv_upper = m.group(1)
                    codes_part = m.group(2)  # np. "D, V"
                    current_voiv_name = pl_lower_name(voiv_upper)

                    letters = re.findall(r"[A-Z]", codes_part)
                    current_voiv_letters = sorted(set(letters))

                    for L in current_voiv_letters:
                        voivodeship_by_first_letter[L] = current_voiv_name
                    continue

                if not current_voiv_name or not current_voiv_letters:
                    continue

                # wpisy powiatów
                for em in RX_ENTRY.finditer(ln):
                    name = em.group("name").strip()
                    v1 = em.group("voiv")
                    v2 = em.group("voiv2")
                    codes_raw = em.group("codes")

                    voiv_letters = [v1]
                    if v2:
                        voiv_letters.append(v2)

                    codes = [c.strip() for c in codes_raw.split(",")]
                    codes = [c for c in codes if c and c != "-"]

                    for VL in voiv_letters:
                        voiv_name = voivodeship_by_first_letter.get(VL, current_voiv_name)
                        for c in codes:
                            full = f"{VL}{c}"
                            if not (2 <= len(full) <= 3):
                                continue
                            if not re.fullmatch(r"[A-Z0-9]{2,3}", full):
                                continue

                            # preferuj „pierwsze znalezione” (żeby nie mieszać)
                            known_prefixes_optional.setdefault(full, f"{name} / {voiv_name}")

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sources": [PAP_PDF_URL, ELI_DU_PDF_URL],
        "voivodeship_by_first_letter": dict(sorted(voivodeship_by_first_letter.items())),
        "known_prefixes_optional": dict(sorted(known_prefixes_optional.items(), key=lambda x: (len(x[0]), x[0]))),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[OK] Wygenerowano:", OUT)
    print("     województwa:", len(payload["voivodeship_by_first_letter"]))
    print("     prefiksy:", len(payload["known_prefixes_optional"]))
    print("     TEST ERA ->", payload["known_prefixes_optional"].get("ERA"))


if __name__ == "__main__":
    main()
