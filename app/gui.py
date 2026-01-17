from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Any

import numpy as np
import cv2
from mss import mss

from PyQt6.QtCore import Qt, QTimer, QThread, QRect, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QMessageBox,
    QCheckBox,
)

from app.region_select import RegionSelectOverlay
from app.ocr import PlateOcr
from app.pl_prefix import region_for_plate
from app.db import get_plate_info, upsert_plate, delete_plate


# Regex dla PL (1-3 litery + 4-5 znaków alnum) => np. ERA75TM, KR1234A
PL_PLATE_RX = re.compile(r"^[A-Z]{1,3}[A-Z0-9]{4,5}$")


def normalize_plate_text(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9]", "", s)  # usuń spacje i znaki specjalne
    return s


def best_plate_from_candidates(candidates: Any) -> Optional[str]:
    """
    Próbuje wyciągnąć sensowną tablicę z listy kandydatów (zależnie od tego jak PlateOcr to zwraca).
    candidates może być np: [("ERA75TM", 0.9), ("ERA75TN", 0.7)] albo ["ERA75TM", ...]
    """
    if not candidates:
        return None

    parsed = []
    for c in candidates:
        if isinstance(c, (list, tuple)) and len(c) >= 1:
            txt = str(c[0])
            conf = 0.0
            if len(c) >= 2:
                try:
                    conf = float(c[1])
                except Exception:
                    conf = 0.0
        else:
            txt = str(c)
            conf = 0.0
        parsed.append((txt, conf))

    parsed.sort(key=lambda x: x[1], reverse=True)

    # 1) twarde dopasowanie regex
    for txt, _ in parsed:
        norm = normalize_plate_text(txt)
        if PL_PLATE_RX.match(norm):
            return norm

    # 2) proste zamiany typowych pomyłek OCR
    swaps_a = str.maketrans({"O": "0", "I": "1", "Z": "2", "S": "5"})
    swaps_b = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S"})

    for txt, _ in parsed:
        norm = normalize_plate_text(txt)
        if 5 <= len(norm) <= 8:
            v1 = norm.translate(swaps_a)
            if PL_PLATE_RX.match(v1):
                return v1
            v2 = norm.translate(swaps_b)
            if PL_PLATE_RX.match(v2):
                return v2

    return None


def bgr_to_pixmap(img_bgr: np.ndarray) -> QPixmap:
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = img_rgb.shape
    bytes_per_line = ch * w
    qimg = QImage(img_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def crop_non_black(img_bgr: np.ndarray) -> np.ndarray:
    """
    Obcina czarne marginesy (typowe gdy zaznaczasz obszar z okna „Zdjęcia” z czarnym tłem).
    """
    try:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        mask = (gray > 12).astype(np.uint8) * 255
        if cv2.countNonZero(mask) < 0.10 * mask.size:
            return img_bgr  # za mało treści, nie tnij

        x, y, w, h = cv2.boundingRect(mask)
        # nie tnij jeśli wyjdzie mikro wycinek
        if w * h < 0.30 * (img_bgr.shape[0] * img_bgr.shape[1]):
            return img_bgr
        return img_bgr[y:y + h, x:x + w]
    except Exception:
        return img_bgr


@dataclass
class AppState:
    region: Optional[QRect] = None
    running: bool = False


class OcrWorker(QThread):
    # object zamiast dict – bezpieczniejsze między wątkami (numpy w środku)
    resultReady = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop = False
        self._region: Optional[QRect] = None
        self._interval_ms = 1000

        # dwa OCR-y: preprocessing i bez (fallback)
        self._ocr_pre = PlateOcr(use_preprocessing=True, gpu=False)
        self._ocr_raw = PlateOcr(use_preprocessing=False, gpu=False)
        self._prefer_pre = True

        # pamięć ostatniego sensownego wyniku (żeby nie znikało przez 1-2 klatki)
        self._last_plate: Optional[str] = None
        self._last_conf: float = 0.0
        self._last_time: float = 0.0
        self._hold_ms = 1200  # ile ms trzymać ostatni wynik gdy OCR zgubi tablicę

    def configure(self, region: QRect, interval_ms: int, use_preprocessing: bool):
        self._region = region
        self._interval_ms = interval_ms
        self._prefer_pre = bool(use_preprocessing)

    def stop(self):
        self._stop = True

    def _try_one(self, ocr: PlateOcr, img_bgr: np.ndarray) -> Tuple[Optional[str], float, Any]:
        res = ocr.read_plate(img_bgr)
        plate = normalize_plate_text(res.plate) if getattr(res, "plate", None) else None
        conf = float(getattr(res, "confidence", 0.0) or 0.0)
        candidates = getattr(res, "raw_candidates", []) or []

        if not plate:
            plate = best_plate_from_candidates(candidates)

        # jeśli plate jest, ale ma śmieci – wywal
        if plate and not PL_PLATE_RX.match(plate):
            plate = None

        return plate, conf, candidates

    def _run_ocr(self, img_bgr: np.ndarray) -> Tuple[Optional[str], float, Any]:
        primary = self._ocr_pre if self._prefer_pre else self._ocr_raw
        secondary = self._ocr_raw if self._prefer_pre else self._ocr_pre

        # przygotuj warianty obrazu (screen z okna zdjęcia bywa mały / z marginesami)
        variants = []
        v0 = img_bgr
        variants.append(v0)

        v1 = crop_non_black(v0)
        if v1 is not v0:
            variants.append(v1)

        v2 = cv2.resize(v1, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        variants.append(v2)

        # próbuj: primary -> secondary na każdym wariancie
        best_plate = None
        best_conf = -1.0
        best_cand = []

        for v in variants:
            p, c, cand = self._try_one(primary, v)
            if p and c >= best_conf:
                best_plate, best_conf, best_cand = p, c, cand
                if best_conf >= 0.70:
                    break  # wystarczająco dobrze

            p2, c2, cand2 = self._try_one(secondary, v)
            if p2 and c2 >= best_conf:
                best_plate, best_conf, best_cand = p2, c2, cand2
                if best_conf >= 0.70:
                    break

        # jeśli nie znaleziono nic, ale mamy kandydatów – spróbuj jeszcze wydłubać „best” bez patrzenia na conf
        if not best_plate:
            # weź kandydatów z ostatniej próby (jeśli były)
            maybe = best_plate_from_candidates(best_cand)
            if maybe and PL_PLATE_RX.match(maybe):
                best_plate = maybe
                best_conf = max(best_conf, 0.50)

        return best_plate, float(best_conf if best_conf >= 0 else 0.0), best_cand

    def run(self):
        try:
            if self._region is None:
                return

            with mss() as sct:
                while not self._stop:
                    t0 = time.time()

                    r = self._region
                    monitor = {
                        "left": r.x(),
                        "top": r.y(),
                        "width": r.width(),
                        "height": r.height(),
                    }
                    shot = np.array(sct.grab(monitor))  # BGRA
                    img_bgr = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

                    plate, conf, candidates = self._run_ocr(img_bgr)

                    now = time.time() * 1000.0

                    # HOLD: jeśli OCR zgubił, trzymaj ostatni wynik chwilę
                    if not plate and self._last_plate and (now - self._last_time) <= self._hold_ms:
                        plate = self._last_plate
                        conf = self._last_conf
                    elif plate:
                        self._last_plate = plate
                        self._last_conf = conf
                        self._last_time = now

                    reg = region_for_plate(plate) if plate else None
                    info = get_plate_info(plate) if plate else None

                    elapsed_ms = (time.time() - t0) * 1000.0

                    self.resultReady.emit({
                        "img_bgr": img_bgr,
                        "plate": plate,
                        "confidence": conf,
                        "region": reg,
                        "db_info": info,
                        "elapsed_ms": elapsed_ms,
                        "candidates": candidates,
                    })

                    sleep_ms = max(10, self._interval_ms - int(elapsed_ms))
                    self.msleep(sleep_ms)

        except Exception as e:
            self.error.emit(f"OcrWorker exception: {e!r}")


class InfoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANPR – Informacje")
        self.resize(520, 420)

        self.lblPlate = QLabel("Tablica: —")
        self.lblRegion = QLabel("Region: —")
        self.lblConf = QLabel("Pewność OCR: —")
        self.lblLast = QLabel("Ostatnia aktualizacja: —")

        self.txtDb = QTextEdit()
        self.txtDb.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self.lblPlate)
        layout.addWidget(self.lblRegion)
        layout.addWidget(self.lblConf)
        layout.addWidget(self.lblLast)
        layout.addWidget(QLabel("Wpis z lokalnej bazy:"))
        layout.addWidget(self.txtDb)
        self.setLayout(layout)

    def update_info(self, plate: Optional[str], region: Optional[str], conf: float,
                    db_info: Optional[dict], elapsed_ms: float):
        self.lblPlate.setText(f"Tablica: {plate or '—'}")
        self.lblRegion.setText(f"Region: {region or '—'}")
        self.lblConf.setText(f"Pewność OCR: {conf:.2f}")
        self.lblLast.setText(f"Ostatnia aktualizacja: {elapsed_ms:.0f} ms")

        if db_info:
            self.txtDb.setPlainText(
                f"tag: {db_info.get('tag', '')}\n"
                f"opis: {db_info.get('opis', '')}"
            )
        else:
            self.txtDb.setPlainText("Brak wpisu w bazie.")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANPR – Screen Demo (Windows)")
        self.resize(720, 520)

        self.state = AppState()
        self._overlay = None  # RegionSelectOverlay

        self.worker = OcrWorker()
        self.worker.resultReady.connect(self.on_worker_result)
        self.worker.error.connect(self.on_worker_error)

        self.infoWin = InfoWindow()
        self.infoWin.show()
        self.infoWin.raise_()
        self.infoWin.activateWindow()

        # przyciski sterujące
        self.btnSelect = QPushButton("Wybierz obszar ekranu")
        self.btnStart = QPushButton("Start")
        self.btnStop = QPushButton("Stop")
        self.btnStop.setEnabled(False)

        self.chkPre = QCheckBox("Preprocessing (polecane)")
        self.chkPre.setChecked(True)

        self.preview = QLabel("Podgląd obszaru pojawi się po starcie…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(260)

        # baza lokalna
        self.edPlate = QLineEdit()
        self.edPlate.setPlaceholderText("np. KR1234A")
        self.edOpis = QLineEdit()
        self.edOpis.setPlaceholderText("Opis (np. Auto testowe)")
        self.edTag = QLineEdit()
        self.edTag.setPlaceholderText("Tag (opcjonalnie)")

        self.btnAdd = QPushButton("Dodaj / Aktualizuj wpis")
        self.btnDel = QPushButton("Usuń wpis")

        # layout
        top = QHBoxLayout()
        top.addWidget(self.btnSelect)
        top.addWidget(self.btnStart)
        top.addWidget(self.btnStop)
        top.addWidget(self.chkPre)

        form = QHBoxLayout()
        form.addWidget(self.edPlate)
        form.addWidget(self.edOpis)
        form.addWidget(self.edTag)
        form.addWidget(self.btnAdd)
        form.addWidget(self.btnDel)

        root = QVBoxLayout()
        root.addLayout(top)
        root.addWidget(self.preview)
        root.addWidget(QLabel("Baza lokalna (offline):"))
        root.addLayout(form)

        self.setLayout(root)

        # akcje
        self.btnSelect.clicked.connect(self.select_region)
        self.btnStart.clicked.connect(self.start)
        self.btnStop.clicked.connect(self.stop)
        self.btnAdd.clicked.connect(self.add_entry)
        self.btnDel.clicked.connect(self.del_entry)

        # automatycznie poproś o wybór obszaru na start
        QTimer.singleShot(200, self.select_region)

    def _close_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.hide()
                self._overlay.close()
                self._overlay.deleteLater()
            except Exception:
                pass
            self._overlay = None

    def select_region(self):
        self._close_overlay()

        self._overlay = RegionSelectOverlay()

        # overlay ma być zawsze na wierzchu, bo inaczej bywa „pod spodem”
        try:
            self._overlay.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self._overlay.setWindowModality(Qt.WindowModality.ApplicationModal)
        except Exception:
            pass

        self._overlay.regionSelected.connect(self.on_region_selected)
        self._overlay.cancelled.connect(self.on_region_cancelled)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def on_region_cancelled(self):
        self._close_overlay()

    def on_region_selected(self, rect: QRect):
        self.state.region = rect

        # najpierw zamknij overlay (bo potrafi blokować kliknięcia)
        self._close_overlay()

        # messagebox dopiero po zamknięciu overlaya
        QTimer.singleShot(0, lambda: QMessageBox.information(
            self,
            "OK",
            f"Zapisano obszar: x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}",
        ))

    def start(self):
        if not self.state.region:
            QMessageBox.warning(self, "Brak obszaru", "Najpierw wybierz obszar ekranu.")
            return
        if self.state.running:
            return

        self.state.running = True
        self.btnStart.setEnabled(False)
        self.btnStop.setEnabled(True)

        self.worker._stop = False
        self.worker.configure(
            region=self.state.region,
            interval_ms=400,
            use_preprocessing=self.chkPre.isChecked(),
        )
        self.worker.start()

    def stop(self):
        if not self.state.running:
            return

        self.state.running = False
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)

        self.worker.stop()
        self.worker.wait(1500)

    def closeEvent(self, event):
        try:
            self.stop()
        finally:
            self.infoWin.close()
            event.accept()

    def add_entry(self):
        plate = normalize_plate_text(self.edPlate.text() or "")
        opis = (self.edOpis.text() or "").strip()
        tag = (self.edTag.text() or "").strip()

        if not plate or not opis:
            QMessageBox.warning(self, "Brak danych", "Wpisz tablicę i opis.")
            return

        upsert_plate(plate, opis, tag)
        QMessageBox.information(self, "Zapisano", f"Zapisano wpis dla {plate}.")

    def del_entry(self):
        plate = normalize_plate_text(self.edPlate.text() or "")
        if not plate:
            QMessageBox.warning(self, "Brak danych", "Wpisz tablicę do usunięcia.")
            return

        ok = delete_plate(plate)
        QMessageBox.information(self, "OK", f"Usunięto {plate}." if ok else f"Brak {plate} w bazie.")

    def on_worker_error(self, msg: str):
        print("[WORKER ERROR]", msg)

    def on_worker_result(self, payload: object):
        try:
            data = dict(payload)
        except Exception:
            print("[DEBUG] payload nie jest dict:", type(payload))
            return

        img_bgr = data["img_bgr"]
        plate = data.get("plate")
        conf = float(data.get("confidence", 0.0))
        region = data.get("region")
        db_info = data.get("db_info")
        elapsed_ms = float(data.get("elapsed_ms", 0.0))
        candidates = data.get("candidates", [])

        print(f"[RESULT] plate={plate} region={region} conf={conf:.2f} ms={elapsed_ms:.0f}")

        pix = bgr_to_pixmap(img_bgr)
        self.preview.setPixmap(
            pix.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        if not self.infoWin.isVisible():
            self.infoWin.show()
        self.infoWin.raise_()

        self.infoWin.update_info(plate, region, conf, db_info, elapsed_ms)

        if plate:
            self.edPlate.setText(plate)

        self.preview.setToolTip(f"czas: {elapsed_ms:.0f} ms\nkandydaci: {candidates}")


def main():
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()
