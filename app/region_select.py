from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QGuiApplication
from PyQt6.QtWidgets import QWidget


class RegionSelectOverlay(QWidget):
    regionSelected = pyqtSignal(QRect)   # globalny QRect (współrzędne ekranu)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Zawsze na wierzchu + narzędziowe okno (żeby nie robić bałaganu w taskbar)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._origin_local: QPoint | None = None
        self._current_local: QPoint | None = None
        self._selection_local = QRect()

        self._set_virtual_geometry()

    def _set_virtual_geometry(self) -> None:
        # obejmij wszystkie monitory (virtual desktop)
        rect = QRect()
        for s in QGuiApplication.screens():
            rect = rect.united(s.geometry())

        if rect.isNull():
            ps = QGuiApplication.primaryScreen()
            rect = ps.geometry() if ps else QRect(0, 0, 800, 600)

        self.setGeometry(rect)

    def force_topmost(self) -> None:
        # czasem Windows/Qt potrafi zgubić fokus
        self.raise_()
        self.activateWindow()

    def _emit_and_close(self, global_rect: QRect) -> None:
        self.regionSelected.emit(global_rect)
        self.close()
        self.deleteLater()

    def _cancel_and_close(self) -> None:
        self.cancelled.emit()
        self.close()
        self.deleteLater()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_and_close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin_local = event.position().toPoint()
            self._current_local = self._origin_local
            self._selection_local = QRect(self._origin_local, self._origin_local)
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel_and_close()

    def mouseMoveEvent(self, event):
        if self._origin_local is None:
            return
        self._current_local = event.position().toPoint()
        self._selection_local = QRect(self._origin_local, self._current_local).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._origin_local is None:
            return

        sel = self._selection_local.normalized()

        # minimalny rozmiar, żeby nie łapać przypadkiem 1px
        if sel.width() < 20 or sel.height() < 20:
            self._origin_local = None
            self._current_local = None
            self._selection_local = QRect()
            self.update()
            return

        # local -> global (uwzględnia x/y geometry okna overlay)
        global_rect = QRect(
            sel.x() + self.geometry().x(),
            sel.y() + self.geometry().y(),
            sel.width(),
            sel.height(),
        )

        self._emit_and_close(global_rect)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # przyciemnienie
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        # instrukcja
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(20, 30, "Zaznacz obszar LPM. Esc / PPM = anuluj.")

        if not self._selection_local.isNull() and self._selection_local.width() > 0:
            # wycięcie (jaśniejszy obszar)
            sel = self._selection_local.normalized()

            p.fillRect(sel, QColor(0, 0, 0, 40))

            pen = QPen(QColor(0, 200, 255, 255))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(sel)

            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(sel.x(), max(15, sel.y() - 6), f"{sel.width()} x {sel.height()}")
