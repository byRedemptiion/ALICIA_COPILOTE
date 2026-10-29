"""Choisir l'IA d'ALICIA et coller sa clé, sans ouvrir de fichier.

Affiché au premier lancement quand aucune clé n'est configurée, puis à tout moment
depuis le bouton « IA » du panneau ou le menu du rond. La clé est écrite dans
%APPDATA%\\Alicia\\.env, sur ce PC seulement, et n'apparaît jamais dans le journal.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from alicia.core.ai.providers.gemini import KEY_URL, check_gemini_key
from alicia.core.config import GeminiSettings
from alicia.ui.theme import PINK, STYLESHEET, title_font

OLLAMA_URL = "https://ollama.com/download"


class _Bridge(QObject):
    checked = Signal(object)  # message d'erreur ou None


class SetupDialog(QDialog):
    """Retourne (fournisseur, clé) via `choice` quand l'utilisateur valide."""

    def __init__(
        self,
        provider: str = "gemini",
        has_key: bool = False,
        parent=None,  # type: ignore[no-untyped-def]
        gemini: GeminiSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.gemini_settings = gemini
        self.setWindowTitle("ALICIA — choisis ton IA")
        self.setStyleSheet(STYLESHEET + "QDialog { background: #060c30; }")
        self.setMinimumWidth(560)
        self.choice: tuple[str, str] | None = None
        self._bridge = _Bridge()
        self._bridge.checked.connect(self._checked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("CHOISIS LE CERVEAU D'ALICIA")
        title.setFont(title_font(15))
        title.setStyleSheet(f"color:{PINK};")
        layout.addWidget(title)
        intro = QLabel(
            "ALICIA a besoin d'une IA pour comprendre ton écran et te répondre. "
            "Ta clé reste sur ce PC (jamais partagée, jamais affichée dans le journal)."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.gemini = QRadioButton("Gemini (Google) — recommandé, gratuit pour commencer")
        self.ollama = QRadioButton("Ollama — IA locale sur ton PC (avancé)")
        group = QButtonGroup(self)
        group.addButton(self.gemini)
        group.addButton(self.ollama)
        (self.ollama if provider == "ollama" else self.gemini).setChecked(True)
        layout.addWidget(self.gemini)

        self.gemini_box = QFrame()
        self.gemini_box.setObjectName("panel")
        box = QVBoxLayout(self.gemini_box)
        box.setContentsMargins(16, 12, 16, 12)
        step1 = QLabel("1. Crée ta clé gratuite (compte Google, 1 minute) :")
        open_page = QPushButton("Ouvrir la page Gemini pour créer ma clé  ↗")
        open_page.setObjectName("primary")
        open_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KEY_URL)))
        step2 = QLabel("2. Clique sur « Create API key », copie-la et colle-la ici :")
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText(
            "Clé déjà enregistrée : laisse vide pour la garder" if has_key else "Colle ta clé ici"
        )
        self.test_button = QPushButton("Tester")
        self.test_button.clicked.connect(self.test_key)
        row = QHBoxLayout()
        row.addWidget(self.key_input, 1)
        row.addWidget(self.test_button)
        for widget in (step1, open_page, step2):
            box.addWidget(widget)
        box.addLayout(row)
        layout.addWidget(self.gemini_box)

        layout.addWidget(self.ollama)
        self.ollama_box = QFrame()
        self.ollama_box.setObjectName("panel")
        obox = QVBoxLayout(self.ollama_box)
        obox.setContentsMargins(16, 12, 16, 12)
        ollama_help = QLabel(
            "Installe Ollama puis un modèle qui voit les images (par ex. « ollama pull gemma3 »). "
            "Gratuit et hors ligne, mais il faut une bonne carte graphique, et c'est plus lent "
            "et moins précis que Gemini."
        )
        ollama_help.setWordWrap(True)
        ollama_help.setObjectName("muted")
        open_ollama = QPushButton("Télécharger Ollama  ↗")
        open_ollama.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OLLAMA_URL)))
        obox.addWidget(ollama_help)
        obox.addWidget(open_ollama)
        layout.addWidget(self.ollama_box)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        later = QPushButton("Plus tard")
        later.setObjectName("ghost")
        later.clicked.connect(self.reject)
        self.save_button = QPushButton("Enregistrer")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(later)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.gemini.toggled.connect(self._sync)
        self._has_key = has_key
        self._sync()

    def _sync(self) -> None:
        self.gemini_box.setVisible(self.gemini.isChecked())
        self.ollama_box.setVisible(self.ollama.isChecked())
        self.adjustSize()

    def provider(self) -> str:
        return "ollama" if self.ollama.isChecked() else "gemini"

    def test_key(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            self.status.setText("Colle d'abord ta clé.")
            return
        self.test_button.setEnabled(False)
        self.status.setText("Vérification de la clé auprès de Google…")
        threading.Thread(
            target=lambda: self._bridge.checked.emit(check_gemini_key(key, self.gemini_settings)),
            daemon=True,
        ).start()

    def _checked(self, problem: str | None) -> None:
        self.test_button.setEnabled(True)
        self.status.setText(f"⚠ {problem}" if problem else "✓ Clé valide : tu peux enregistrer.")

    def save(self) -> None:
        key = self.key_input.text().strip()
        if self.provider() == "gemini" and not key and not self._has_key:
            self.status.setText("Colle ta clé Gemini (ou choisis « Plus tard »).")
            return
        self.choice = (self.provider(), key)
        self.accept()
