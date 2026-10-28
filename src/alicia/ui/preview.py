from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class CapturePreview(QLabel):
    """Garde l’image entière visible quand la disposition change."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.original = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    def setPixmap(self, pixmap):
        self.original = QPixmap(pixmap)
        self._fit()

    def clear(self):
        self.original = QPixmap()
        super().clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if not self.original.isNull():
            super().setPixmap(
                self.original.scaled(
                    self.contentsRect().size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
