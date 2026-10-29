import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Aucun test ne lit le vrai .env, les vraies clés ni le dossier utilisateur."""
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ALICE_AI_PROVIDER", "ALICE_LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    yield
