import hashlib
import io
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import httpx
import pytest

from alicia.audio import model_setup
from alicia.audio.ports import SpeechError


def zip_archive(extra_entries=(), *, complete=True):
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as bundle:
        files = {
            "am/final.mdl": b"synthetic-acoustic-model-for-tests",
            "conf/model.conf": b"--beam=10",
            "conf/mfcc.conf": b"--sample-frequency=16000",
            "graph/HCLr.fst": b"synthetic-graph-for-tests",
        }
        if not complete:
            files.pop("am/final.mdl")
        for name, content in files.items():
            bundle.writestr(model_setup.MODEL_NAME + "/" + name, content)
        for name, content in extra_entries:
            bundle.writestr(name, content)
    return output.getvalue()


def write_model(target):
    with ZipFile(io.BytesIO(zip_archive())) as bundle:
        bundle.extractall(target.parent)
    return target


def client_for(archive, requests=None, *, status=200):
    def handle(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(status, content=archive)

    return httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)


def assert_no_partial_model(target):
    assert not target.exists()
    assert not list(target.parent.glob("alicia-model-*"))


def test_explicit_download_uses_official_https_and_records_transparency_metadata(tmp_path):
    target = tmp_path / model_setup.MODEL_NAME
    archive = zip_archive()
    requests = []
    with client_for(archive, requests) as client:
        assert model_setup.prepare_voice_model(target, client) == target
        assert not client.is_closed, "Injected clients remain owned by their caller"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == model_setup.MODEL_URL
    assert request.url.scheme == "https"
    assert request.url.host == "alphacephei.com"
    assert not request.content
    assert model_setup.model_is_present(target)
    metadata = json.loads((target / ".alicia-model.json").read_text(encoding="utf-8"))
    assert metadata["archive_sha256"] == hashlib.sha256(archive).hexdigest()
    assert metadata["source"] == model_setup.MODEL_URL
    assert "pas de signature indépendante" in metadata["integrity"]
    assert "downloaded_at" in metadata
    assert not list(tmp_path.glob("alicia-model-*"))


def test_present_model_is_idempotent_and_never_creates_network_client(tmp_path, monkeypatch):
    target = write_model(tmp_path / model_setup.MODEL_NAME)
    client_factory = Mock(side_effect=AssertionError("Network must not be opened"))
    monkeypatch.setattr(model_setup.httpx, "Client", client_factory)
    assert model_setup.prepare_voice_model(target) == target
    client_factory.assert_not_called()


@pytest.mark.parametrize("existing_kind", ["directory", "file"])
def test_incomplete_existing_target_is_preserved_without_network(tmp_path, existing_kind):
    target = tmp_path / model_setup.MODEL_NAME
    if existing_kind == "directory":
        target.mkdir()
        preserved = target / "user-file.txt"
    else:
        preserved = target
    preserved.write_text("existing user work", encoding="utf-8")
    requests = []
    with (
        client_for(zip_archive(), requests) as client,
        pytest.raises(SpeechError, match="incomplet"),
    ):
        model_setup.prepare_voice_model(target, client)
    assert preserved.read_text(encoding="utf-8") == "existing user work"
    assert requests == []


def test_broken_symlink_target_is_not_replaced(tmp_path):
    target = tmp_path / model_setup.MODEL_NAME
    try:
        target.symlink_to(tmp_path / "missing-user-model", target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable on this platform")
    requests = []
    with client_for(zip_archive(), requests) as client, pytest.raises(SpeechError):
        model_setup.prepare_voice_model(target, client)
    assert target.is_symlink()
    assert requests == []


@pytest.mark.parametrize("graph_kind", ["empty-file", "directory"])
def test_graph_must_be_a_nonempty_regular_file(tmp_path, graph_kind):
    target = write_model(tmp_path / model_setup.MODEL_NAME)
    graph = target / "graph" / "HCLr.fst"
    graph.unlink()
    if graph_kind == "directory":
        graph.mkdir()
    else:
        graph.touch()
    assert not model_setup.model_is_present(target)


@pytest.mark.parametrize(
    "entry",
    [
        "../escape.txt",
        "/absolute.txt",
        model_setup.MODEL_NAME + "/../../escape.txt",
        model_setup.MODEL_NAME + "/C:escape.txt",
        model_setup.MODEL_NAME + "\\escape.txt",
        "another-model/am/final.mdl",
    ],
)
def test_archive_traversal_or_unexpected_root_is_rejected_and_cleaned(tmp_path, entry):
    target = tmp_path / model_setup.MODEL_NAME
    with client_for(zip_archive(((entry, b"unsafe"),))) as client:
        with pytest.raises(SpeechError, match="chemin invalide"):
            model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)
    assert not (tmp_path / "escape.txt").exists()


def test_archive_symlink_is_rejected_before_extraction(tmp_path):
    target = tmp_path / model_setup.MODEL_NAME
    link = ZipInfo(model_setup.MODEL_NAME + "/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = zip_archive(((link, b"../../outside"),))
    with client_for(archive) as client, pytest.raises(SpeechError, match="chemin invalide"):
        model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)


@pytest.mark.parametrize("content", [b"not a zip-private-content", zip_archive(complete=False)])
def test_corrupt_or_incomplete_archive_never_installs_partial_model(tmp_path, content):
    target = tmp_path / model_setup.MODEL_NAME
    with client_for(content) as client, pytest.raises(SpeechError) as error:
        model_setup.prepare_voice_model(target, client)
    assert "private-content" not in str(error.value)
    assert_no_partial_model(target)


def test_bad_crc_is_rejected_and_cleaned(tmp_path):
    target = tmp_path / model_setup.MODEL_NAME
    archive = zip_archive().replace(
        b"synthetic-acoustic-model-for-tests", b"corrupted-acoustic-model-for-tests", 1
    )
    with client_for(archive) as client, pytest.raises(SpeechError):
        model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)


def test_download_size_limit_aborts_before_install(tmp_path, monkeypatch):
    target = tmp_path / model_setup.MODEL_NAME
    monkeypatch.setattr(model_setup, "MAX_DOWNLOAD", 10)
    with client_for(zip_archive()) as client, pytest.raises(SpeechError, match="taille"):
        model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)


def test_extracted_size_limit_aborts_before_install(tmp_path, monkeypatch):
    target = tmp_path / model_setup.MODEL_NAME
    monkeypatch.setattr(model_setup, "MAX_EXTRACTED", 10)
    with client_for(zip_archive()) as client, pytest.raises(SpeechError, match="limites"):
        model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)


def test_excessive_archive_entry_count_is_rejected(tmp_path):
    target = tmp_path / model_setup.MODEL_NAME
    extras = ((f"{model_setup.MODEL_NAME}/files/{index}.txt", b"") for index in range(5000))
    with client_for(zip_archive(extras)) as client, pytest.raises(SpeechError, match="limites"):
        model_setup.prepare_voice_model(target, client)
    assert_no_partial_model(target)


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_failures_never_follow_redirects_or_leak_body(tmp_path, status):
    target = tmp_path / model_setup.MODEL_NAME
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://example.com/unsafe"},
            text="private server message",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(SpeechError) as error:
            model_setup.prepare_voice_model(target, client)
    assert len(requests) == 1
    assert "private" not in str(error.value)
    assert_no_partial_model(target)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_tls_or_network_errors_are_sanitized_and_leave_no_partial_files(tmp_path, failure):
    target = tmp_path / model_setup.MODEL_NAME

    def fail(request):
        raise failure("TLS certificate private-error-information", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(SpeechError) as error:
            model_setup.prepare_voice_model(target, client)
    assert "private-error-information" not in str(error.value)
    assert_no_partial_model(target)


def test_owned_http_client_preserves_tls_verification_and_is_closed(tmp_path, monkeypatch):
    target = tmp_path / model_setup.MODEL_NAME
    client = client_for(zip_archive())
    factory = Mock(return_value=client)
    monkeypatch.setattr(model_setup.httpx, "Client", factory)
    assert model_setup.prepare_voice_model(target) == target
    assert factory.call_args.kwargs.get("verify", True) is True
    assert factory.call_args.kwargs["follow_redirects"] is False
    assert client.is_closed


def test_prepare_voice_cli_is_explicit_and_does_not_start_application(
    tmp_path, monkeypatch, capsys
):
    from alicia import config
    from alicia.__main__ import main

    target = tmp_path / model_setup.MODEL_NAME
    prepare = Mock(return_value=target)
    monkeypatch.setattr(model_setup, "prepare_voice_model", prepare)
    monkeypatch.setattr(config, "load_settings", lambda: SimpleNamespace(voice_model_path=target))
    assert main(["--prepare-voice"]) == 0
    prepare.assert_called_once_with(target)
    assert "prêt" in capsys.readouterr().out


def test_prepare_voice_cli_reports_safe_setup_failure(monkeypatch, capsys):
    from alicia import config
    from alicia.__main__ import main

    monkeypatch.setattr(
        config, "load_settings", lambda: SimpleNamespace(voice_model_path=Path("x"))
    )
    monkeypatch.setattr(
        model_setup, "prepare_voice_model", Mock(side_effect=OSError("private path"))
    )
    assert main(["--prepare-voice"]) == 2
    captured = capsys.readouterr()
    assert "private path" not in captured.err
    assert "inaccessible" in captured.err


@pytest.mark.parametrize("other_flag", ["--demo", "--smoke-test", "--screenshot=preview.png"])
def test_prepare_voice_cli_rejects_mixed_modes_without_network(other_flag, monkeypatch):
    from alicia.__main__ import main

    prepare = Mock(side_effect=AssertionError("No download for invalid arguments"))
    monkeypatch.setattr(model_setup, "prepare_voice_model", prepare)
    with pytest.raises(SystemExit) as error:
        main(["--prepare-voice", other_flag])
    assert error.value.code == 2
    prepare.assert_not_called()
