import json
from pathlib import Path

import pytest

from alicia.audio.ports import SpeechError
from alicia.audio.whisper_setup import (
    WHISPER_REPOSITORY,
    prepare_whisper_model,
    whisper_model_is_present,
)


def model_files(path: Path, vocabulary="vocabulary.txt"):
    path.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json", vocabulary):
        (path / name).write_bytes(b"model fixture")


def test_explicit_preparation_uses_official_repository_and_is_repeatable(tmp_path):
    calls = []

    def download(**arguments):
        calls.append(arguments)
        staging = Path(arguments["local_dir"])
        model_files(staging)
        (staging / ".cache").mkdir()
        (staging / ".cache" / "metadata").write_text("cache")

    target = tmp_path / "whisper"
    assert prepare_whisper_model(target, download) == target
    assert whisper_model_is_present(target)
    assert not (target / ".cache").exists()
    assert calls[0]["repo_id"] == WHISPER_REPOSITORY
    assert calls[0]["max_workers"] == 2
    assert "model.bin" in calls[0]["allow_patterns"]
    assert "vocabulary.*" in calls[0]["allow_patterns"]
    record = json.loads((target / ".alicia-model.json").read_text(encoding="utf-8"))
    assert len(record["sha256"]["model.bin"]) == 64
    assert "pas de signature" in record["integrity"]
    assert prepare_whisper_model(target, download) == target
    assert len(calls) == 1


def test_vocabulary_json_is_supported(tmp_path):
    model_files(tmp_path, "vocabulary.json")
    assert whisper_model_is_present(tmp_path)


@pytest.mark.parametrize("name", ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"])
def test_missing_or_empty_model_files_are_not_ready(tmp_path, name):
    model_files(tmp_path)
    (tmp_path / name).write_bytes(b"")
    assert not whisper_model_is_present(tmp_path)


def test_existing_incomplete_user_folder_is_preserved(tmp_path):
    target = tmp_path / "whisper"
    target.mkdir()
    (target / "user.txt").write_text("preserve")
    called = []
    with pytest.raises(SpeechError, match="incomplet"):
        prepare_whisper_model(target, lambda **kwargs: called.append(kwargs))
    assert (target / "user.txt").read_text() == "preserve"
    assert called == []


def test_existing_symlink_is_not_replaced(tmp_path):
    target = tmp_path / "whisper"
    try:
        target.symlink_to(tmp_path / "absent", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires extra privileges on this Windows runner")
    with pytest.raises(SpeechError, match="lien"):
        prepare_whisper_model(target, lambda **kwargs: pytest.fail("No download"))
    assert target.is_symlink()


def test_failed_download_is_safe_and_leaves_no_partial_target(tmp_path):
    def download(**arguments):
        staging = Path(arguments["local_dir"])
        staging.mkdir()
        (staging / "partial.bin").write_bytes(b"partial")
        raise RuntimeError("private proxy credential detail")

    target = tmp_path / "whisper"
    with pytest.raises(SpeechError) as error:
        prepare_whisper_model(target, download)
    assert "private" not in str(error.value)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_without_all_required_files_does_not_publish_model(tmp_path):
    def download(**arguments):
        Path(arguments["local_dir"]).mkdir()

    target = tmp_path / "whisper"
    with pytest.raises(SpeechError, match="fichiers"):
        prepare_whisper_model(target, download)
    assert not target.exists()


def test_symlinked_download_file_is_rejected(tmp_path):
    source = tmp_path / "external.bin"
    source.write_bytes(b"keep me")

    def download(**arguments):
        staging = Path(arguments["local_dir"])
        model_files(staging)
        (staging / "model.bin").unlink()
        try:
            (staging / "model.bin").symlink_to(source)
        except OSError:
            pytest.skip("Creating symlinks requires extra privileges on this Windows runner")

    target = tmp_path / "whisper"
    with pytest.raises(SpeechError, match="invalide"):
        prepare_whisper_model(target, download)
    assert source.read_bytes() == b"keep me"
    assert not target.exists()


def test_oversized_download_is_not_published(tmp_path, monkeypatch):
    from alicia.audio import whisper_setup

    monkeypatch.setattr(whisper_setup, "MAX_MODEL_BYTES", 10)

    def download(**arguments):
        model_files(Path(arguments["local_dir"]))

    target = tmp_path / "whisper"
    with pytest.raises(SpeechError, match="taille"):
        prepare_whisper_model(target, download)
    assert not target.exists()
