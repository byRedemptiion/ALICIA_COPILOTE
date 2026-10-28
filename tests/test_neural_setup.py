import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from alicia.audio import neural_setup
from alicia.audio.ports import SpeechError


def voices_blob(name="ff_siwis.npy", content=b"\x93NUMPYfixture"):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def small_fixture_models(monkeypatch):
    monkeypatch.setattr(neural_setup, "MODEL_MIN_BYTES", 4)
    monkeypatch.setattr(
        neural_setup,
        "ASSET_BYTES",
        {
            "kokoro-v1.0.onnx": len(b"onnx fixture"),
            "voices-v1.0.bin": len(voices_blob()),
        },
    )


def client_for(model=b"onnx fixture", voices=None, *, second_status=200):
    calls = []
    voices = voices_blob() if voices is None else voices

    def handle(request):
        calls.append(request)
        if request.url.path.endswith(".onnx"):
            return httpx.Response(200, content=model)
        return httpx.Response(second_status, content=voices)

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def test_explicit_setup_downloads_fixed_https_assets_and_records_integrity(tmp_path):
    target = tmp_path / "voice"
    client, calls = client_for()
    try:
        assert neural_setup.prepare_neural_voice(target, client) == target
        assert [str(call.url) for call in calls] == list(neural_setup.ASSETS.values())
        assert all(call.url.scheme == "https" for call in calls)
        assert neural_setup.neural_voice_is_present(target)
        manifest = json.loads((target / ".alicia-neural.json").read_text())
        assert manifest["release"] == "model-files-v1.1"
        assert "sans signature indépendante" in manifest["integrity"]
        assert len(manifest["files"]["kokoro-v1.0.onnx"]["sha256"]) == 64
    finally:
        client.close()


def test_ready_installation_skips_network_and_does_not_close_injected_client(tmp_path):
    target = tmp_path / "voice"
    client, calls = client_for()
    neural_setup.prepare_neural_voice(target, client)
    neural_setup.prepare_neural_voice(target, client)
    assert len(calls) == 2
    assert not client.is_closed
    client.close()


@pytest.mark.parametrize("change", ["model", "manifest", "size", "source", "missing"])
def test_changed_installation_is_not_ready_and_is_preserved(tmp_path, change):
    target = tmp_path / "voice"
    client, calls = client_for()
    neural_setup.prepare_neural_voice(target, client)
    if change == "model":
        (target / "kokoro-v1.0.onnx").write_bytes(b"changed file")
    elif change == "manifest":
        (target / ".alicia-neural.json").write_text("invalid json")
    elif change == "missing":
        (target / "voices-v1.0.bin").unlink()
    else:
        path = target / ".alicia-neural.json"
        data = json.loads(path.read_text())
        data["files"]["kokoro-v1.0.onnx"][change] = (
            999 if change == "size" else "https://elsewhere.example/model"
        )
        path.write_text(json.dumps(data))
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    assert not neural_setup.neural_voice_is_present(target)
    with pytest.raises(SpeechError, match="existe"):
        neural_setup.prepare_neural_voice(target, client)
    assert before == {path.name: path.read_bytes() for path in target.iterdir()}
    assert len(calls) == 2
    client.close()


def test_existing_unknown_directory_is_never_overwritten(tmp_path):
    target = tmp_path / "voice"
    target.mkdir()
    (target / "personal.txt").write_text("keep")
    with pytest.raises(SpeechError, match="existe"):
        neural_setup.prepare_neural_voice(target)
    assert (target / "personal.txt").read_text() == "keep"


@pytest.mark.parametrize("dangling", [True, False])
def test_symlink_target_is_preserved(tmp_path, dangling):
    source = tmp_path / "source"
    if not dangling:
        source.mkdir()
    target = tmp_path / "voice"
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not available on this machine")
    with pytest.raises(SpeechError, match="lien symbolique"):
        neural_setup.prepare_neural_voice(target)
    assert target.is_symlink()


@pytest.mark.parametrize(
    "model,voices",
    [
        (b"", None),
        (b"ok", None),
        (b"good model", b"not a ZIP"),
        (b"good model", voices_blob("af_other.npy")),
        (b"good model", voices_blob(content=b"not numpy")),
    ],
)
def test_invalid_assets_never_leave_partial_target(tmp_path, model, voices):
    target = tmp_path / "voice"
    client, _ = client_for(model, voices)
    with pytest.raises(SpeechError):
        neural_setup.prepare_neural_voice(target, client)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    client.close()


@pytest.mark.parametrize(
    "voice_name,content", [("af_other.npy", b"\x93NUMPYfixture"), ("ff_siwis.npy", b"not numpy")]
)
def test_voice_validation_runs_after_successful_length_checks(
    tmp_path, monkeypatch, voice_name, content
):
    blob = voices_blob(voice_name, content)
    monkeypatch.setitem(neural_setup.ASSET_BYTES, "voices-v1.0.bin", len(blob))
    client, _ = client_for(voices=blob)
    with pytest.raises(SpeechError, match="française"):
        neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert not (tmp_path / "voice").exists()
    client.close()


def test_corrupt_voice_crc_is_rejected(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("ff_siwis.npy", b"\x93NUMPYvoice-data")
    blob = bytearray(buffer.getvalue())
    blob[blob.index(b"voice-data")] ^= 1
    monkeypatch.setitem(neural_setup.ASSET_BYTES, "voices-v1.0.bin", len(blob))
    client, _ = client_for(voices=bytes(blob))
    with pytest.raises(SpeechError, match="corrompue"):
        neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert list(tmp_path.iterdir()) == []
    client.close()


def test_missing_second_asset_cleans_first_download(tmp_path):
    target = tmp_path / "voice"
    client, _ = client_for(second_status=404)
    with pytest.raises(SpeechError, match="inaccessible"):
        neural_setup.prepare_neural_voice(target, client)
    assert list(tmp_path.iterdir()) == []
    client.close()


def test_combined_download_limit_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(neural_setup, "MAX_DOWNLOAD_BYTES", 15)
    client, _ = client_for()
    with pytest.raises(SpeechError, match="taille"):
        neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert list(tmp_path.iterdir()) == []
    client.close()


@pytest.mark.parametrize(
    "location",
    [
        "http://github.com/file",
        "https://evil.example/file",
        "https://user:pass@github.com/file",
        "https://github.com:444/file",
        "https://github.com/file#fragment",
    ],
)
def test_redirects_stay_on_official_https_asset_hosts(tmp_path, location):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": location})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SpeechError, match="redirection"):
            neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_official_asset_redirect_is_followed(tmp_path):
    def handle(request):
        if request.url.host == "github.com" and request.url.path.endswith(".onnx"):
            return httpx.Response(
                302,
                headers={"Location": "https://release-assets.githubusercontent.com/fixture/model"},
            )
        if request.url.host == "release-assets.githubusercontent.com":
            return httpx.Response(200, content=b"onnx fixture")
        return httpx.Response(200, content=voices_blob())

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        target = neural_setup.prepare_neural_voice(tmp_path / "voice", client)
        assert neural_setup.neural_voice_is_present(target)


def test_redirect_loop_is_bounded(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": str(request.url)})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SpeechError, match="redirection"):
            neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert len(calls) == 4


def test_network_errors_are_sanitized(tmp_path):
    def handle(request):
        raise httpx.ConnectError("private-data", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SpeechError) as caught:
            neural_setup.prepare_neural_voice(tmp_path / "voice", client)
    assert "private-data" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_owned_client_keeps_tls_verification_and_is_closed(tmp_path, monkeypatch):
    real_client = httpx.Client
    created = []

    def construct(**kwargs):
        assert kwargs.get("verify", True) is True
        client = real_client(transport=httpx.MockTransport(lambda _: httpx.Response(403)), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(neural_setup.httpx, "Client", construct)
    with pytest.raises(SpeechError):
        neural_setup.prepare_neural_voice(tmp_path / "voice")
    assert created[0].is_closed


def test_target_created_during_download_is_preserved(tmp_path):
    target = tmp_path / "voice"

    def handle(request):
        if request.url.path.endswith(".onnx"):
            return httpx.Response(200, content=b"onnx fixture")
        target.mkdir()
        (target / "personal").write_text("keep")
        return httpx.Response(200, content=voices_blob())

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SpeechError, match="créé pendant"):
            neural_setup.prepare_neural_voice(target, client)
    assert (target / "personal").read_text() == "keep"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["voice"]
