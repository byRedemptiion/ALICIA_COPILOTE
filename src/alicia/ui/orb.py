"""Mode bulle : seul le rond d'ALICIA reste à l'écran, et ses paroles s'affichent à côté.

Le rond est une petite fenêtre sans bord, transparente et toujours au-dessus des autres.
On le déplace à la souris ; double-clic = panneau complet ; clic droit = menu.
La bulle de texte n'apparaît que pendant un échange, puis s'efface toute seule. Elle ne
prend jamais le focus ; on peut la glisser où l'on veut (elle suit ensuite le rond).

Les deux fenêtres sont exclues des captures d'écran (Windows 10 2004+), pour qu'ALICIA ne
se voie pas elle-même dans l'image envoyée à l'IA.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QVBoxLayout, QWidget

from alicia.ui.core_widget import AliciaCore
from alicia.ui.theme import GOLD, STYLESHEET, TEXT

log = logging.getLogger("alicia.ui")

WDA_EXCLUDEFROMCAPTURE = 0x11
BUBBLE_WIDTH = 400
MAX_BUBBLE_CHARS = 900
MARGIN = 24


def exclude_from_capture(widget: QWidget) -> None:
    """Demande à Windows de ne pas inclure cette fenêtre dans les captures."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ok = ctypes.windll.user32.SetWindowDisplayAffinity(  # type: ignore[attr-defined]
            int(widget.winId()), WDA_EXCLUDEFROMCAPTURE
        )
        if not ok:
            log.debug("Exclusion de capture refusée par Windows pour %s", widget.objectName())
    except Exception as exc:  # noqa: BLE001 - simple confort, jamais bloquant
        log.debug("Exclusion de capture impossible : %r", exc)


def _rich(text: str) -> str:
    """Markdown simple (gras, listes) → HTML compact, sans les marges de paragraphe."""
    lines = []
    for raw in text.strip().splitlines():
        line = html.escape(raw.strip())
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*]\s+", "• ", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#ff8cc0'>\1</b>", line)
        lines.append(line)
    return "<br>".join(lines)


def _tail(text: str) -> str:
    """Pour une très longue réponse, on garde la fin (la bulle n'a pas d'ascenseur)."""
    text = text.strip()
    if len(text) <= MAX_BUBBLE_CHARS:
        return text
    cut = text[-MAX_BUBBLE_CHARS:]
    space = cut.find(" ")
    return "…" + (cut[space:] if 0 <= space < 40 else cut)


class Bubble(QWidget):
    """Bulle de dialogue à côté du rond : ta question, puis la réponse d'ALICIA."""

    moved = Signal()  # le joueur l'a déplacée : sa place relative au rond est à retenir

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("aliciaBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            STYLESHEET
            + f"""
            QFrame#bubble {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(14, 22, 74, 0.94), stop:1 rgba(5, 9, 38, 0.94));
                border: 1px solid rgba(255, 61, 139, 0.75);
                border-radius: 16px;
            }}
            QLabel#bubbleAsked {{ color: {GOLD}; font-size: 10pt; }}
            QLabel#bubbleText {{ color: {TEXT}; font-size: 11.5pt; }}
            """
        )
        frame = QFrame(self)
        frame.setObjectName("bubble")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(16, 12, 16, 14)
        inner.setSpacing(6)
        self.asked = QLabel("")
        self.asked.setObjectName("bubbleAsked")
        self.asked.setWordWrap(True)
        self.text = QLabel("")
        self.text.setObjectName("bubbleText")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(self.asked)
        inner.addWidget(self.text)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        self.setFixedWidth(BUBBLE_WIDTH)
        self.setToolTip("Glisser : déplacer · double-clic : fermer · clic droit : recoller au rond")
        self._buffer = ""
        self._anchor = QRect()
        self.offset: QPoint | None = None  # place choisie par le joueur, relative au rond
        self._drag: QPoint | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(260)
        self._fade.finished.connect(self._fade_finished)

    # --- contenu --------------------------------------------------------------------------------

    def ask(self, question: str) -> None:
        self._buffer = ""
        self.asked.setText(f"TOI  ›  {question}" if question else "")
        self.asked.setVisible(bool(question))
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setText("…")
        self._pop()

    def set_question(self, question: str) -> None:
        self.asked.setText(f"TOI  ›  {question}")
        self.asked.setVisible(True)
        self._relayout()

    def append(self, delta: str) -> None:
        self._buffer += delta
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setText(_tail(self._buffer.replace("**", "")))
        self._pop()

    def set_answer(self, text: str) -> None:
        self._buffer = text
        if len(text) <= MAX_BUBBLE_CHARS:
            self.text.setTextFormat(Qt.TextFormat.RichText)
            self.text.setText(_rich(text))
        else:
            self.text.setTextFormat(Qt.TextFormat.PlainText)
            self.text.setText(_tail(text.replace("**", "")))
        self._pop()

    def notice(self, text: str, hide_ms: int = 7000) -> None:
        """Message court d'ALICIA (avertissement, consigne), sans question."""
        self._buffer = text
        self.asked.setVisible(False)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setText(text)
        self._pop()
        self.hide_after(hide_ms)

    # --- affichage ------------------------------------------------------------------------------

    def follow(self, orb: QRect) -> None:
        self._anchor = QRect(orb)
        self._place()

    def hide_after(self, ms: int) -> None:
        self._hide_timer.start(max(500, ms))

    def keep(self) -> None:
        self._hide_timer.stop()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _fade_finished(self) -> None:
        if self.windowOpacity() <= 0.01:
            self.hide()

    def _pop(self) -> None:
        self._hide_timer.stop()
        self._fade.stop()
        self._relayout()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            exclude_from_capture(self)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self.setWindowOpacity(1.0)

    def _relayout(self) -> None:
        # Hauteur calculée à la main : adjustSize() se trompe avec les textes à la ligne.
        inner = BUBBLE_WIDTH - 32
        height = 12 + 14 + 2 + max(self.text.heightForWidth(inner), 18)
        if not self.asked.isHidden():
            height += self.asked.heightForWidth(inner) + 6
        self.setFixedHeight(height)
        self._place()

    # --- déplacement à la souris -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.keep()  # on ne la fait pas disparaître pendant qu'on la tient
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.reset_offset()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None:
            self._drag = None
            if not self._anchor.isNull():
                self.offset = self.pos() - self._anchor.topLeft()
                self.moved.emit()
            self.hide_after(6000)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.fade_out()

    def reset_offset(self) -> None:
        self.offset = None
        self._place()
        self.moved.emit()

    def _place(self) -> None:
        if self._anchor.isNull():
            return
        screen = QGuiApplication.screenAt(self._anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        gap = 10
        if self.offset is not None:  # place choisie par le joueur, gardée à l'écran
            point = self._anchor.topLeft() + self.offset
            x = max(area.left(), min(point.x(), area.right() - self.width()))
            y = max(area.top(), min(point.y(), area.bottom() - self.height()))
            self.move(x, y)
            return
        # À gauche du rond s'il est dans la moitié droite de l'écran, sinon à droite.
        if self._anchor.center().x() > area.center().x():
            x = self._anchor.left() - self.width() - gap
        else:
            x = self._anchor.right() + gap
        y = self._anchor.center().y() - min(self.height(), self._anchor.height()) // 2
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
        self.move(x, y)


class OrbWindow(QWidget):
    """Le rond d'ALICIA, seul à l'écran."""

    open_panel = Signal()
    stop_voice = Signal()
    quit_requested = Signal()
    game_chosen = Signal(str)
    update_requested = Signal()
    wake_toggled = Signal(bool)
    setup_requested = Signal()

    def __init__(self, size: int = 210, position_file: Path | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("aliciaOrb")
        self.setWindowTitle("ALICIA")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.position_file = position_file
        self.core = AliciaCore(self, show_labels=False, minimum=size)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.core)
        self.setFixedSize(size, size)
        self.setToolTip(
            "ALICIA — maintiens F10 pour lui parler, F9 pour une analyse rapide.\n"
            "Glisser : déplacer · double-clic : panneau complet · clic droit : menu"
        )
        self.bubble = Bubble()
        self.bubble.moved.connect(self._save_position)
        self.games: list[tuple[str, str]] = []  # (clé, nom) proposés dans le menu « Jeu »
        self.current_game = "auto"
        self.wake_on = False
        self._drag: QPoint | None = None
        self._placed = False

    # --- position -------------------------------------------------------------------------------

    def _default_position(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        return QPoint(area.right() - self.width() - MARGIN, area.top() + MARGIN + 40)

    def _saved_position(self) -> QPoint | None:
        if self.position_file is None:
            return None
        try:
            data = json.loads(self.position_file.read_text(encoding="utf-8"))
            point = QPoint(int(data["x"]), int(data["y"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if "bubble_dx" in data and "bubble_dy" in data:
            try:
                self.bubble.offset = QPoint(int(data["bubble_dx"]), int(data["bubble_dy"]))
            except (TypeError, ValueError):
                self.bubble.offset = None
        center = point + QPoint(self.width() // 2, self.height() // 2)
        return point if QGuiApplication.screenAt(center) is not None else None

    def _save_position(self) -> None:
        if self.position_file is None:
            return
        try:
            self.position_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"x": self.x(), "y": self.y()}
            if self.bubble.offset is not None:
                data["bubble_dx"] = self.bubble.offset.x()
                data["bubble_dy"] = self.bubble.offset.y()
            self.position_file.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            log.debug("Position du rond non enregistrée : %r", exc)

    # --- événements -----------------------------------------------------------------------------

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if not self._placed:
            self.move(self._saved_position() or self._default_position())
            self._placed = True
        super().showEvent(event)
        exclude_from_capture(self)
        self.bubble.follow(self.frameGeometry())

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().hideEvent(event)
        self.bubble.keep()
        self.bubble.hide()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.bubble.close()
        super().closeEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().moveEvent(event)
        self.bubble.follow(self.frameGeometry())

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._save_position()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.open_panel.emit()

    def contextMenuEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#0a1240; color:#e9eeff; border:1px solid #ff3d8b; padding:4px; }"
            "QMenu::item { padding:6px 18px; border-radius:6px; }"
            "QMenu::item:selected { background: rgba(255,61,139,0.35); }"
        )
        actions = (
            ("Ouvrir le panneau complet", self.open_panel.emit),
            ("Couper la voix", self.stop_voice.emit),
            ("Masquer la bulle", self.bubble.fade_out),
            ("Recoller la bulle au rond", self.bubble.reset_offset),
            (
                "Réveil « Alicia » : activé ✓" if self.wake_on else "Réveil « Alicia » : coupé",
                lambda: self.wake_toggled.emit(not self.wake_on),
            ),
            ("Choisir l'IA / la clé", self.setup_requested.emit),
            ("Mettre à jour ALICIA", self.update_requested.emit),
            ("Replacer en haut à droite", self._reset_position),
            (None, None),
            ("Quitter ALICIA", self.quit_requested.emit),
        )
        if self.games:
            games = menu.addMenu("Jeu")
            for key, name in self.games:
                action = QAction(name, games)
                action.setCheckable(True)
                action.setChecked(key == self.current_game)
                action.triggered.connect(lambda _=False, k=key: self.game_chosen.emit(k))
                games.addAction(action)
            menu.addSeparator()
        for text, slot in actions:
            if text is None:
                menu.addSeparator()
                continue
            action = QAction(text, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.exec(event.globalPos())

    def _reset_position(self) -> None:
        self.move(self._default_position())
        self._save_position()
