import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from alicia.audio import chatterbox_setup as setup
from alicia.audio.ports import SpeechError


@pytest.fixture
def reference(tmp_path):
    path = tmp_path / "female-synthetic.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 32000)
    return path


def downloader(**kwargs):
    assert kwargs["repo_id"] == "ResembleAI/chatterbox"
    assert kwargs["allow_patterns"] == list(setup.CHATTERBOX_FILES)
    assert kwargs["max_workers"] == 2
    target = Path(kwargs["local_dir"])
    target.mkdir(parents=True)
    for name in setup.CHATTERBOX_FILES:
        (target / name).write_bytes(b"test weights")


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/tools/uv" if name == "uv" else None)
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] <= 1800
        if "venv" in arguments:
            python = setup.runtime_python(Path(arguments[-1]))
            python.parent.mkdir(parents=True)
            python.write_bytes(b"fake python")
        return SimpleNamespace(returncode=0)

    return run, calls


def test_explicit_installation_is_separate_pinned_and_repeatable(tmp_path, reference, runner):
    run, calls = runner
    runtime, model = tmp_path / "runtime", tmp_path / "model"
    assert (
        setup.prepare_expressive_voice(runtime, model, reference, downloader=downloader, runner=run)
        == model
    )
    assert setup.chatterbox_voice_is_present(runtime, model)
    assert len(calls) == 4
    assert "https://download.pytorch.org/whl/cpu" in calls[1][0]
    assert "chatterbox-tts==0.1.7" in calls[2][0]
    assert (model / "reference.wav").read_bytes() == reference.read_bytes()
    manifest = json.loads((model / ".alicia-expressive.json").read_text())
    assert "sans signature indépendante" in manifest["integrity"]
    assert setup.prepare_expressive_voice(runtime, model) == model
    assert len(calls) == 4


def test_explicit_cuda_uses_official_torch_index(tmp_path, reference, runner):
    run, calls = runner
    setup.prepare_expressive_voice(
        tmp_path / "runtime",
        tmp_path / "model",
        reference,
        device="cuda",
        downloader=downloader,
        runner=run,
    )
    assert "https://download.pytorch.org/whl/cu124" in calls[1][0]


def test_network_failure_happens_before_heavy_runtime_install(tmp_path, reference, runner):
    run, calls = runner

    def unavailable(**kwargs):
        raise RuntimeError("private headers and authentication")

    with pytest.raises(SpeechError) as error:
        setup.prepare_expressive_voice(
            tmp_path / "runtime", tmp_path / "model", reference, downloader=unavailable, runner=run
        )
    assert "private" not in str(error.value)
    assert not calls
    assert not (tmp_path / "runtime").exists()
    assert not (tmp_path / "model").exists()


def test_failed_runtime_keeps_downloaded_model_and_cleans_owned_runtime(
    tmp_path, reference, runner
):
    run, _ = runner

    def fails(arguments, **kwargs):
        if "install" in arguments:
            return SimpleNamespace(returncode=1)
        return run(arguments, **kwargs)

    runtime, model = tmp_path / "runtime", tmp_path / "model"
    with pytest.raises(SpeechError, match="Installation"):
        setup.prepare_expressive_voice(
            runtime, model, reference, downloader=downloader, runner=fails
        )
    assert setup.expressive_model_is_present(model)
    assert not runtime.exists()


@pytest.mark.parametrize("folder", ["runtime", "model"])
def test_existing_incomplete_directory_is_preserved(tmp_path, reference, runner, folder):
    run, _ = runner
    runtime, model = tmp_path / "runtime", tmp_path / "model"
    existing = tmp_path / folder
    existing.mkdir()
    (existing / "personal.txt").write_text("keep")
    with pytest.raises(SpeechError, match="existe"):
        setup.prepare_expressive_voice(runtime, model, reference, downloader=downloader, runner=run)
    assert (existing / "personal.txt").read_text() == "keep"


def test_modified_weights_are_rejected_and_not_replaced(tmp_path, reference, runner):
    run, calls = runner
    runtime, model = tmp_path / "runtime", tmp_path / "model"
    setup.prepare_expressive_voice(runtime, model, reference, downloader=downloader, runner=run)
    (model / "ve.pt").write_bytes(b"changed data")
    assert not setup.chatterbox_voice_is_present(runtime, model)
    with pytest.raises(SpeechError, match="existe"):
        setup.prepare_expressive_voice(runtime, model, reference, downloader=downloader, runner=run)
    assert (model / "ve.pt").read_bytes() == b"changed data"
    assert len(calls) == 4


def test_missing_model_file_never_leaves_partial_directory(tmp_path, reference, runner):
    run, _ = runner

    def missing(**kwargs):
        downloader(**kwargs)
        (Path(kwargs["local_dir"]) / "ve.pt").unlink()

    with pytest.raises(SpeechError, match="incomplet"):
        setup.prepare_expressive_voice(
            tmp_path / "runtime", tmp_path / "model", reference, downloader=missing, runner=run
        )
    assert sorted(path.name for path in tmp_path.iterdir()) == [reference.name]


@pytest.mark.parametrize("name", ["runtime", "model"])
def test_symlink_targets_are_never_used(tmp_path, reference, runner, name):
    run, _ = runner
    target = tmp_path / name
    target.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(SpeechError, match="lien symbolique"):
        setup.prepare_expressive_voice(
            tmp_path / "runtime", tmp_path / "model", reference, downloader=downloader, runner=run
        )
    assert target.is_symlink()


def test_invalid_synthetic_reference_is_rejected_without_downloading(tmp_path, runner):
    run, calls = runner
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"not wav")
    with pytest.raises(SpeechError, match="référence"):
        setup.prepare_expressive_voice(
            tmp_path / "runtime", tmp_path / "model", reference, downloader=downloader, runner=run
        )
    assert not calls


def test_size_limit_is_enforced(tmp_path, reference, runner, monkeypatch):
    run, _ = runner
    monkeypatch.setattr(setup, "MAX_MODEL_BYTES", 20)
    with pytest.raises(SpeechError, match="taille"):
        setup.prepare_expressive_voice(
            tmp_path / "runtime", tmp_path / "model", reference, downloader=downloader, runner=run
        )
    assert not (tmp_path / "model").exists()
