"""Read-only application artwork and synthetic voice reference bundled in the wheel."""

from pathlib import Path

ASSET_DIRECTORY = Path(__file__).with_name("assets")
APP_ICON = ASSET_DIRECTORY / "alicia.ico"
DEFAULT_PORTRAIT = ASSET_DIRECTORY / "alicia.png"
VOICE_REFERENCE = ASSET_DIRECTORY / "voice-reference.wav"
