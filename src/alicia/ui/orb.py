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
from alicia.ui.naming import named
from alicia.ui.theme import BG, DEEP, GOLD, PINK, PINK_SOFT, STYLESHEET, TEXT, rgb

log = logging.getLogger("alicia.ui")

WDA_EXCLUDEFROMCAPTURE = 0x11
BUBBLE_WIDTH = 400
MAX_BUBBLE_CHARS = 900
MARGIN = 24


WDA_NONE = 0
# Visible en stream : OBS / Discord voient le rond et la bulle (réglage [ui] stream_visible).
stream_visible = False


def exclude_from_capture(widget: QWidget) -> None:
    """Demande à Windows de ne pas inclure cette fenêtre dans les captures (sauf si le
    joueur veut la montrer en stream)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ok = ctypes.windll.user32.SetWindowDisplayAffinity(  # type: ignore[attr-defined]
            int(widget.winId()), WDA_NONE if stream_visible else WDA_EXCLUDEFROMCAPTURE
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
        line = re.sub(r"\*\*(.+?)\*\*", rf"<b style='color:{PINK_SOFT}'>\1</b>", line)
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
        # Apparence réglable (mode édition du rond)
        self.bubble_width = BUBBLE_WIDTH
        self.font_pt = 11.5
        self.alpha = 0.94  # opacité du fond
        self.side = "auto"  # auto | left | right | above | below
        self.seconds = 4  # temps d'affichage après la fin de la voix
        self.editing = False
        self.apply_style()
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
        self.setFixedWidth(self.bubble_width)
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

    # --- apparence ------------------------------------------------------------------------------

    def apply_style(self) -> None:
        a = max(0.3, min(1.0, self.alpha))
        self.setStyleSheet(
            STYLESHEET
            + f"""
            QFrame#bubble {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({rgb(DEEP)}, {a:.2f}), stop:1 rgba({rgb(BG)}, {a:.2f}));
                border: 1px solid rgba({rgb(PINK)}, 0.75);
                border-radius: 16px;
            }}
            QLabel#bubbleAsked {{ color: {GOLD}; font-size: {self.font_pt * 0.87:.1f}pt; }}
            QLabel#bubbleText {{ color: {TEXT}; font-size: {self.font_pt:.1f}pt; }}
            """
        )
        self.setFixedWidth(int(self.bubble_width))
        if self.isVisible():
            self._relayout()

    def layout_prefs(self) -> dict[str, object]:
        return {
            "bubble_width": int(self.bubble_width),
            "bubble_font": self.font_pt,
            "bubble_alpha": self.alpha,
            "bubble_side": self.side,
            "bubble_seconds": self.seconds,
        }

    def load_prefs(self, data: dict) -> None:  # type: ignore[type-arg]
        try:
            self.bubble_width = max(260, min(800, int(data.get("bubble_width", self.bubble_width))))
            self.font_pt = max(8.0, min(22.0, float(data.get("bubble_font", self.font_pt))))
            self.alpha = max(0.3, min(1.0, float(data.get("bubble_alpha", self.alpha))))
            side = str(data.get("bubble_side", self.side))
            self.side = side if side in ("auto", "left", "right", "above", "below") else "auto"
            self.seconds = max(2, min(60, int(data.get("bubble_seconds", self.seconds))))
        except (TypeError, ValueError):
            pass
        self.apply_style()

    def after_voice_ms(self) -> int:
        return int(self.seconds * 1000)

    def linger_ms(self, text: str) -> int:
        """Sans voix : le temps de lire (au moins le réglage, au plus 30 s)."""
        return int(min(30000, max(self.seconds * 1000 + 2000, len(text) * 55)))

    def show_sample(self) -> None:
        """Mode édition : bulle d'exemple, qui reste affichée."""
        self.asked.setText("TOI  ›  🎙 Quel objet je prends pour cette manche ?")
        self.asked.setVisible(True)
        self.set_answer(
            "Prends **la Lame du crépuscule** : elle colle à ton héros. "
            "Garde ensuite ton or pour le bouclier si l'équipe adverse plonge sur toi."
        )
        self.keep()

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
        if self.editing:
            return  # en mode édition, la bulle d'exemple reste
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
        inner = int(self.bubble_width) - 32
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
        if self.offset is None and self.side != "auto":
            a = self._anchor
            if self.side == "left":
                x, y = a.left() - self.width() - gap, a.center().y() - self.height() // 2
            elif self.side == "right":
                x, y = a.right() + gap, a.center().y() - self.height() // 2
            elif self.side == "above":
                x, y = a.center().x() - self.width() // 2, a.top() - self.height() - gap
            else:
                x, y = a.center().x() - self.width() // 2, a.bottom() + gap
            x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
            y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
            self.move(x, y)
            return
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
    layout_changed = Signal()
    vision_chosen = Signal(str)
    stream_toggled = Signal(bool)

    def __init__(self, size: int = 210, position_file: Path | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )  # sans Qt.Tool : le rond a son icône dans la barre des tâches
        self.setObjectName("aliciaOrb")
        self.setWindowTitle(named("ALICIA"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.position_file = position_file
        self.core = AliciaCore(self, show_labels=False, minimum=size)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.core)
        self.setFixedSize(size, size)
        self.setToolTip(
            named(
                "ALICIA — maintiens F10 pour lui parler, F9 pour une analyse rapide.\n"
                "Glisser : déplacer · double-clic : panneau complet · clic droit : menu"
            )
        )
        self.bubble = Bubble()
        self.bubble.moved.connect(self._save_position)
        self.games: list[tuple[str, str]] = []  # (clé, nom) proposés dans le menu « Jeu »
        self.current_game = "auto"
        self.wake_on = False
        self.vision = "window"
        self._drag: QPoint | None = None
        self._placed = False
        self.size_px = size
        self.edit_panel: EditPanel | None = None
        self._load_prefs()

    # --- taille et préférences d'affichage --------------------------------------------------

    def _read_file(self) -> dict:  # type: ignore[type-arg]
        if self.position_file is None:
            return {}
        try:
            data = json.loads(self.position_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load_prefs(self) -> None:
        data = self._read_file()
        if "orb_size" in data:
            try:
                self.set_orb_size(int(data["orb_size"]), save=False)
            except (TypeError, ValueError):
                pass
        self.bubble.load_prefs(data)

    def set_orb_size(self, size: int, save: bool = True) -> None:
        size = max(120, min(480, int(size)))
        center = self.frameGeometry().center()
        self.size_px = size
        self.core.setMinimumSize(size, size)
        self.setFixedSize(size, size)
        if self._placed:
            self.move(center - QPoint(size // 2, size // 2))
        self.bubble.follow(self.frameGeometry())
        if save:
            self._save_position()

    def start_editing(self) -> None:
        """Mode édition : bulle d'exemple et panneau de réglages à côté du rond."""
        if self.edit_panel is None:
            self.edit_panel = EditPanel(self)
        self.bubble.editing = True
        self.bubble.show_sample()
        self.edit_panel.load()
        self.edit_panel.show()
        self.edit_panel.raise_()
        self.edit_panel.activateWindow()

    def stop_editing(self) -> None:
        self.bubble.editing = False
        self._save_position()
        if self.edit_panel is not None:
            self.edit_panel.hide()
        self.bubble.fade_out()
        self.layout_changed.emit()

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
            data: dict[str, object] = {"x": self.x(), "y": self.y(), "orb_size": self.size_px}
            data.update(self.bubble.layout_prefs())
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

    def set_stream_visible(self, visible: bool) -> None:
        """Montre (ou cache) le rond et la bulle aux logiciels de stream, tout de suite."""
        global stream_visible
        stream_visible = visible
        for window in (self, self.bubble):
            if window.isVisible():
                exclude_from_capture(window)

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
            f"QMenu {{ background:{DEEP}; color:{TEXT}; border:1px solid {PINK}; padding:4px; }}"
            "QMenu::item { padding:6px 18px; border-radius:6px; }"
            f"QMenu::item:selected {{ background: rgba({rgb(PINK)},0.35); }}"
        )
        actions = (
            ("Ouvrir le panneau complet", self.open_panel.emit),
            ("Couper la voix", self.stop_voice.emit),
            ("Mode édition (taille, bulle, texte)…", self.start_editing),
            ("Masquer la bulle", self.bubble.fade_out),
            ("Recoller la bulle au rond", self.bubble.reset_offset),
            (
                "Réveil « Alicia » : activé ✓" if self.wake_on else "Réveil « Alicia » : coupé",
                lambda: self.wake_toggled.emit(not self.wake_on),
            ),
            (
                "Visible en stream (OBS) ✓" if stream_visible else "Visible en stream (OBS)",
                lambda: self.stream_toggled.emit(not stream_visible),
            ),
            ("Choisir l'IA / la clé", self.setup_requested.emit),
            ("Mettre à jour ALICIA", self.update_requested.emit),
            ("Replacer en haut à droite", self._reset_position),
            (None, None),
            ("Quitter ALICIA", self.quit_requested.emit),
        )
        vision = menu.addMenu("Vision")
        for key, label in (
            ("window", "L'application (le jeu)"),
            ("cursor", "Autour du curseur"),
            ("screen", "L'écran entier"),
        ):
            action = QAction(label, vision)
            action.setCheckable(True)
            action.setChecked(key == self.vision)
            action.triggered.connect(lambda _=False, k=key: self.vision_chosen.emit(k))
            vision.addAction(action)
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
            action = QAction(named(text), menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.exec(event.globalPos())

    def _reset_position(self) -> None:
        self.move(self._default_position())
        self._save_position()


class EditPanel(QWidget):
    """Réglages du mode bulle, appliqués en direct : taille du rond, bulle, texte, position."""

    def __init__(self, orb: OrbWindow) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        from PySide6.QtWidgets import QComboBox, QGridLayout, QPushButton, QSlider

        self.orb = orb
        self.setWindowTitle(named("ALICIA — mode édition"))
        self.setStyleSheet(STYLESHEET + "QWidget#editPanel { background: " + DEEP + "; }")
        self.setObjectName("editPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(14)
        title = QLabel("MODE ÉDITION")
        title.setObjectName("sectionTitle")
        grid.addWidget(title, 0, 0, 1, 3)
        hint = QLabel("Glisse le rond et la bulle où tu veux. Les réglages s'appliquent en direct.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        grid.addWidget(hint, 1, 0, 1, 3)

        def slider(lo: int, hi: int) -> QSlider:
            widget = QSlider(Qt.Orientation.Horizontal)
            widget.setRange(lo, hi)
            return widget

        self.size = slider(120, 480)
        self.width_ = slider(260, 800)
        self.font = slider(8, 22)
        self.alpha = slider(30, 100)
        self.seconds = slider(2, 30)
        self.values: dict[QSlider, QLabel] = {}
        rows = (
            ("Taille du rond", self.size, " px"),
            ("Largeur de la bulle", self.width_, " px"),
            ("Taille du texte", self.font, " pt"),
            ("Opacité du fond", self.alpha, " %"),
            ("Reste affichée", self.seconds, " s après la voix"),
        )
        for row, (label, widget, unit) in enumerate(rows, start=2):
            value = QLabel("")
            value.setObjectName("muted")
            value.setMinimumWidth(120)
            self.values[widget] = value
            widget.valueChanged.connect(lambda v, lab=value, u=unit: lab.setText(f"{v}{u}"))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
            grid.addWidget(value, row, 2)
        self.side = QComboBox()
        for key, text in (
            ("auto", "Automatique (côté libre de l'écran)"),
            ("left", "À gauche du rond"),
            ("right", "À droite du rond"),
            ("above", "Au-dessus du rond"),
            ("below", "En dessous du rond"),
        ):
            self.side.addItem(text, key)
        grid.addWidget(QLabel("Place de la bulle"), 7, 0)
        grid.addWidget(self.side, 7, 1, 1, 2)
        reset = QPushButton("Réinitialiser")
        reset.setObjectName("ghost")
        reset.clicked.connect(self.reset)
        done = QPushButton("Terminer")
        done.setObjectName("primary")
        done.clicked.connect(self.orb.stop_editing)
        grid.addWidget(reset, 8, 0)
        grid.addWidget(done, 8, 2)
        self.setMinimumWidth(560)

        self.size.valueChanged.connect(lambda v: self.orb.set_orb_size(v, save=False))
        self.width_.valueChanged.connect(lambda v: self._bubble(bubble_width=v))
        self.font.valueChanged.connect(lambda v: self._bubble(font_pt=float(v)))
        self.alpha.valueChanged.connect(lambda v: self._bubble(alpha=v / 100))
        self.seconds.valueChanged.connect(lambda v: self._bubble(seconds=v))
        self.side.currentIndexChanged.connect(self._side_changed)

    def _bubble(self, **changes: object) -> None:
        bubble = self.orb.bubble
        for key, value in changes.items():
            setattr(bubble, key, value)
        bubble.apply_style()
        bubble.show_sample()

    def _side_changed(self) -> None:
        self.orb.bubble.side = self.side.currentData()
        self.orb.bubble.offset = None  # une place choisie ici remplace celle glissée à la main
        self.orb.bubble.show_sample()

    def load(self) -> None:
        bubble = self.orb.bubble
        self.size.setValue(self.orb.size_px)
        self.width_.setValue(int(bubble.bubble_width))
        self.font.setValue(int(round(bubble.font_pt)))
        self.alpha.setValue(int(bubble.alpha * 100))
        self.seconds.setValue(int(bubble.seconds))
        self.side.setCurrentIndex(max(0, self.side.findData(bubble.side)))
        for widget in self.values:
            widget.valueChanged.emit(widget.value())
        # À côté du rond, sans le cacher
        screen = QGuiApplication.screenAt(self.orb.frameGeometry().center())
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        self.adjustSize()
        x = max(area.left() + 8, self.orb.x() - self.width() - 20)
        y = min(self.orb.y() + self.orb.height() + 20, area.bottom() - self.height() - 8)
        self.move(x, max(area.top() + 8, y))

    def reset(self) -> None:
        self.orb.bubble.offset = None
        self.size.setValue(210)
        self.width_.setValue(BUBBLE_WIDTH)
        self.font.setValue(12)
        self.alpha.setValue(94)
        self.seconds.setValue(4)
        self.side.setCurrentIndex(0)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.orb.bubble.editing:
            self.orb.stop_editing()
        super().closeEvent(event)
