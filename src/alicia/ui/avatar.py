import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class Avatar(QWidget):
    """Visuel original local ; bouche animée pendant la lecture audio réelle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 230)
        self.state = "idle"
        self.phase = 0
        self.picture = QPixmap()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def set_state(self, state: str) -> None:
        self.state = state
        if state in {"speaking", "thinking", "capturing"}:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def load_picture(self, path: str) -> bool:
        picture = QPixmap(path)
        if picture.isNull():
            return False
        self.picture = picture.scaled(600, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.update()
        return True

    def _tick(self):
        self.phase += 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        accent = QColor("#f098a6" if self.state == "error" else "#9aead6")
        radius = 91 + (3 * math.sin(self.phase * 0.5) if self.timer.isActive() else 0)
        painter.setPen(QPen(accent, 2))
        painter.setBrush(QColor("#203d43"))
        painter.drawEllipse(QRectF(-radius, -radius, 2 * radius, 2 * radius))
        if not self.picture.isNull():
            from PySide6.QtGui import QPainterPath

            clip = QPainterPath()
            clip.addEllipse(QRectF(-80, -80, 160, 160))
            painter.save()
            painter.setClipPath(clip)
            scaled = self.picture.scaled(
                160, 160, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
            painter.restore()
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#b8a8e9"))
            painter.drawRoundedRect(QRectF(-62, -73, 124, 144), 58, 58)
            painter.setBrush(QColor("#e0d7fc"))
            painter.drawRoundedRect(QRectF(-48, -57, 96, 114), 43, 43)
            painter.setPen(QPen(QColor("#253347"), 4, Qt.SolidLine, Qt.RoundCap))
            for x in [-20, 20]:
                painter.drawArc(QRectF(x - 9, -15, 18, 12), 0, 180 * 16)
            if self.state == "speaking":
                opening = 4 + abs(math.sin(self.phase * 0.9)) * 12
                painter.setBrush(QColor("#70536d"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QRectF(-10, 22, 20, opening))
            else:
                painter.drawArc(QRectF(-13, 14, 26, 20), 180 * 16, 180 * 16)
            painter.setPen(QPen(accent, 5, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(QRectF(-70, -65, 140, 130), 0, 180 * 16)
            painter.drawLine(69, 0, 69, 32)
            painter.drawLine(69, 32, 42, 41)
        if self.state == "speaking":
            painter.setPen(QPen(accent, 4, Qt.SolidLine, Qt.RoundCap))
            for i in range(9):
                height = 3 + abs(math.sin(self.phase * 0.7 + i)) * 14
                x = (i - 4) * 12
                painter.drawLine(int(x), 108 - int(height), int(x), 108 + int(height))
