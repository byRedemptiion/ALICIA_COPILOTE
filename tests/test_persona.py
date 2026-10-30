import subprocess
import sys

import numpy as np
import pytest

from alicia.core import persona
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.audio.speaker import robot_voice
from alicia.core.audio.wake import find_wake, strip_wake_word


@pytest.fixture
def veris():
    persona.set_current("veris")
    yield persona.current()
    persona.set_current("alicia")


def test_default_is_alicia():
    assert persona.current().key == "alicia"
    assert persona.set_current("inconnu").key == "alicia"
    assert "Tu es Alicia" in build_system_prompt()


def test_veris_identity_and_wake_word(veris):
    assert "Tu es VERIS" in build_system_prompt()
    assert find_wake("Véris, lance Discord") == (True, "lance discord")
    assert find_wake("Ok Verisse quel objet") == (True, "quel objet")
    assert find_wake("Alicia, lance Discord")[0] is False
    assert strip_wake_word("Veris, monte le son") == "monte le son"


def test_names_in_interface(veris, qt_app):
    from alicia.ui.naming import named

    assert named("Mettre à jour ALICIA") == "Mettre à jour VERIS"
    assert named("CE QU'ALICIA SAIT DU JEU") == "CE QUE VERIS SAIT DU JEU"
    assert named("le rond d'ALICIA") == "le rond de VERIS"
    assert named("A · L · I · C · I · A") == "V · E · R · I · S"
    assert named(r"%APPDATA%\Alicia\.env") == r"%APPDATA%\Alicia\.env"


def test_robot_voice_raises_pitch_and_keeps_format():
    rate = 24000
    t = np.arange(rate) / rate
    ratio = 2 ** (450 / 1200)
    samples = (0.3 * np.sin(2 * np.pi * 400 * t) * 32767).astype(np.int16)
    out = robot_voice(samples, ratio)
    assert out.dtype == np.int16
    assert len(out) == round(rate / ratio)
    peak = np.argmax(np.abs(np.fft.rfft(out))) * rate / len(out)
    assert abs(peak - 400 * ratio) < 3


def test_veris_theme_is_violet():
    code = (
        "from alicia.core.persona import set_current; set_current('veris');"
        "from alicia.ui import theme; print(theme.PINK, theme.STATE_COLORS['idle'].name())"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["#7c4dff", "#7c4dff"]


def test_stream_visibility_setting(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.app import build_services
    from alicia.core.config import data_dir, load_settings
    from alicia.ui import orb
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    assert settings.stream_visible is False
    window = MainWindow(build_services(settings, demo=True))
    window.settings_page.stream_box.setChecked(True)
    assert orb.stream_visible is True
    saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
    assert saved["ui"]["stream_visible"] is True
    window.orb.stream_toggled.emit(False)
    assert orb.stream_visible is False
    assert window.settings_page.stream_box.isChecked() is False
    window.close()


def test_veris_is_masculine_in_the_interface(veris, qt_app):
    from alicia.ui.naming import named

    assert named("ALICIA se réveille toute seule quand elle t'entend") == (
        "VERIS se réveille tout seul quand il t'entend"
    )
