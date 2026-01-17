# ANPR Screen Demo (PL) – OCR tablic rejestracyjnych z ekranu

![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

Aplikacja demonstracyjna z GUI (Windows), która pozwala zaznaczyć fragment ekranu (np. zdjęcie/film z tablicą rejestracyjną) i cyklicznie rozpoznaje polskie tablice rejestracyjne metodą OCR.

W osobnym oknie wyświetla:
- **Rozpoznaną tablicę**,
- **Pewność OCR** (confidence),
- **Region** (powiat/województwo) na podstawie prefiksu tablicy (offline),
- **Dane z lokalnej bazy** `plates_db.json` (offline): opis i tag.

> ⚠️ **Uwaga:** Projekt edukacyjny/demonstracyjny: nie łączy się z rejestrami właścicieli pojazdów i nie identyfikuje osób.

---

## 📑 Spis treści
1. [Funkcje](#-funkcje)
2. [Wymagania](#-wymagania)
3. [Instalacja i uruchomienie](#-instalacja--uruchomienie-od-zera)
4. [Jak testować (Użycie)](#-jak-testować-ocr-ze-screena)
5. [Baza danych i Regiony](#-lokalna-baza-tablic-i-regiony)
6. [Struktura projektu](#-struktura-projektu)
7. [Rozwiązywanie problemów](#-troubleshooting)

---

## ✨ Funkcje

- ✅ **Overlay ekranowy**: Zaznaczenie obszaru ekranu i OCR w pętli.
- ✅ **Stabilizacja OCR**: Fallbacki, crop marginesów, awaryjny upscale, funkcja „hold" wyniku (zapobiega miganiu).
- ✅ **Regiony PL (offline)**: Rozpoznawanie powiatu/województwa na podstawie prefiksu tablicy (baza JSON).
- ✅ **Lokalna baza (offline)**: Dodawanie, aktualizacja i usuwanie własnych opisów/tagów dla tablic.
- ✅ **Podgląd na żywo**: Okno informacyjne aktualizowane w czasie rzeczywistym.

---

## ⚙️ Wymagania

- **System**: Windows 10/11
- **Python**: 3.12.x (zalecane)
- **Narzędzia**: pip, git

---

## 🚀 Instalacja + uruchomienie (od zera)

### 1. Pobranie projektu
```bash
git clone <URL_DO_TWOJEGO_REPO>
cd anpr-screen-demo
```

### 2. Utworzenie środowiska i instalacja zależności
```bash
python -m venv .venv

# Aktywacja środowiska (Windows CMD):
.venv\Scripts\activate
# LUB (PowerShell):
.venv\Scripts\activate.ps1

# Instalacja bibliotek:
pip install -r requirements.txt
```

> **Wskazówka:** Jeśli PowerShell blokuje aktywację venv, wpisz:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 3. (Opcjonalnie) Aktualizacja mapy regionów PL
Skrypt pobiera dane i zapisuje mapę do `data/prefix_map_pl.json`.

```bash
python scripts/update_prefix_map_from_pap_pdf.py
```
*Szybki test mapy:*
```bash
python -c "from app.pl_prefix import region_for_plate; print(region_for_plate('ERA75TM'))"
```

### 4. Start aplikacji
```bash
python run.py
```

---

## 📸 Jak testować (OCR ze screena)

1. **Przygotuj obraz**: Otwórz zdjęcie lub film z tablicą rejestracyjną (najlepiej powiększ tablicę, aby była czytelna).
2. **Wybierz obszar**:
   - W aplikacji kliknij **"Wybierz obszar ekranu"**.
   - Zaznacz **możliwie ciasno** samą tablicę (unikaj zbędnego tła i czarnych pasów).
3. **Start**: Kliknij **"Start"**.
4. **Wyniki**:
   Sprawdź okno „ANPR – Informacje", gdzie zobaczysz:
   - **Tablica**: rozpoznany numer.
   - **Region**: powiat/województwo.
   - **Wpis z bazy**: opis/tag (jeśli istnieje).

---

## 💾 Lokalna baza tablic i Regiony

### Plik bazy danych
Dane są przechowywane w pliku `data/plates_db.json`.

**Przykładowa struktura:**
```json
{
  "KR1234A": { "opis": "Auto testowe #1", "tag": "TEST" },
  "WA9876B": { "opis": "Auto testowe #2", "tag": "TEST" },
  "ERA75TM": { "opis": "Test – auto z neta", "tag": "DEMO" }
}
```

### Edycja bazy w GUI
W dolnej części głównego okna możesz zarządzać wpisami:
1. Wpisz numer **Tablicy** (np. `ERA75TM`).
2. Dodaj **Opis** i **Tag**.
3. Użyj przycisków:
   - `Dodaj / Aktualizuj wpis` – zapisuje zmiany.
   - `Usuń wpis` – kasuje dane tablicy.

---

## 📂 Struktura projektu

```text
anpr-screen-demo/
├── app/
│   ├── gui.py           # Główna logika GUI + worker OCR (screen capture)
│   ├── region_select.py # Overlay do zaznaczania obszaru ekranu
│   ├── ocr.py           # Logika przetwarzania obrazu i OCR
│   ├── pl_prefix.py     # Mapowanie prefiksów tablic na regiony
│   └── db.py            # Obsługa pliku JSON (odczyt/zapis)
├── data/
│   ├── plates_db.json     # Lokalna baza opisów i tagów
│   └── prefix_map_pl.json # Mapa regionów (generowana skryptem)
├── scripts/
│   └── update_prefix_map_from_pap_pdf.py # Generator mapy regionów
├── run.py               # Punkt startowy aplikacji
├── requirements.txt     # Lista zależności
└── README.md            # Dokumentacja
```

---

## 🔧 Troubleshooting (Rozwiązywanie problemów)

### Drugie okno nic nie pokazuje
* **Przyczyna**: OCR nie rozpoznał tekstu lub pewność (confidence) jest zbyt niska.
* **Rozwiązanie**: Upewnij się, że zaznaczony obszar zawiera tablicę. **Powiększ (zrób zoom)** tablicy na ekranie – więcej pikseli to lepszy odczyt.

### Region wyświetla się jako „—"
* **Przyczyna**: Brak mapy prefiksów lub tablica spoza bazy.
* **Rozwiązanie**: Wygeneruj mapę komendą:
  `python scripts/update_prefix_map_from_pap_pdf.py`

### Aplikacja działa wolno / obciąża CPU
* **Rozwiązanie**:
  1. Zaznacz mniejszy obszar ekranu.
  2. Zwiększ `interval_ms` w pliku `app/gui.py` (np. na 800–1000 ms), aby skanować rzadziej.

---

## 📜 Licencja

Projekt udostępniony na licencji MIT (lub innej - do uzupełnienia).
