from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

BASE = "https://tablica-rejestracyjna.pl"
OUT = Path(__file__).resolve().parent.parent / "data" / "prefix_map_pl.json"

RE_VOIV = re.compile(r"^([A-Z])\s*-\s*wojew[óo]dztwo\s*(.+)$", re.IGNORECASE)
RE_POWIAT = re.compile(r"^([A-Z]{1,3})\s*-\s*powiat\s*(.+)$", re.IGNORECASE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": BASE + "/",
    "Connection": "keep-alive",
}


def fetch(session: requests.Session, url: str, tries: int = 3, sleep_s: float = 0.8) -> str:
    last_exc = None
    for i in range(tries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            if r.status_code == 403:
                raise requests.HTTPError("403 Forbidden (blokada anty-bot / brak dostępu)", response=r)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            last_exc = e
            time.sleep(sleep_s * (i + 1))
    raise last_exc


def parse_home_for_voiv_and_letters(html: str) -> Tuple[Dict[str, str], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    voiv = {}
    letters = set()

    # na stronie głównej są linki typu "E - województwo łódzkie"
    for a in soup.find_all("a"):
        txt = a.get_text(" ", strip=True)
        m = RE_VOIV.match(txt)
        if m:
            letter = m.group(1).upper()
            name = m.group(2).strip().lower()
            voiv[letter] = name
            letters.add(letter)

    # fallback
    if not letters:
        letters = set(list("BCDEFGKLMNOPRSTWZ"))

    return voiv, sorted(letters)


def parse_letter_page_for_powiat_prefixes(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    out = {}

    # na stronach /E, /K, ... są linki typu "ERA - powiat radomszczański"
    for a in soup.find_all("a"):
        txt = a.get_text(" ", strip=True)
        m = RE_POWIAT.match(txt)
        if m:
            prefix = m.group(1).upper().strip()
            powiat = re.sub(r"\s+", " ", m.group(2).strip())
            out[prefix] = powiat

    return out


def main():
    session = requests.Session()

    home = fetch(session, BASE + "/")
    voiv_map, letters = parse_home_for_voiv_and_letters(home)

    known_prefixes_optional: Dict[str, str] = {}

    # pobierz powiaty z każdej litery
    for letter in letters:
        html = fetch(session, f"{BASE}/{letter}")
        powiat_map = parse_letter_page_for_powiat_prefixes(html)

        # budujemy wpis: "powiat ... / województwo ..."
        voiv = voiv_map.get(letter)
        for pref, powiat in powiat_map.items():
            if voiv:
                known_prefixes_optional[pref] = f"{powiat} / {voiv}"
            else:
                known_prefixes_optional[pref] = powiat

        time.sleep(0.4)  # grzecznie, żeby nie spamować

    # zbuduj plik wynikowy w Twoim formacie
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": BASE,
        "voivodeship_by_first_letter": voiv_map,
        "known_prefixes_optional": dict(sorted(known_prefixes_optional.items(), key=lambda x: (len(x[0]), x[0]))),
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Zapisano: {OUT}")
    print(f"     Prefiksów: {len(known_prefixes_optional)}")
    print(f"     Województw: {len(voiv_map)}")

    # szybki test kontrolny
    test = "ERA"
    print(f"     TEST {test}: {payload['known_prefixes_optional'].get(test)}")


if __name__ == "__main__":
    main()
