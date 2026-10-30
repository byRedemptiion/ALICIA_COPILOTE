import time

import httpx
import pytest

from alicia.core.duo import DuoKeys, DuoLink, new_code, parse_duo_request


def test_messages_are_encrypted_and_signed():
    keys = DuoKeys("ABCD-EFGH-JKLM-NPQR")
    sealed = keys.seal({"text": "Salut Alicia !"})
    assert "Salut" not in sealed
    assert keys.open(sealed) == {"text": "Salut Alicia !"}
    assert DuoKeys("AUTRE-CODE").open(sealed) is None  # mauvais code : rejeté
    tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    assert keys.open(tampered) is None
    assert keys.topic == DuoKeys("ABCD-EFGH-JKLM-NPQR").topic != DuoKeys("x").topic


def test_new_code_format():
    code = new_code()
    assert len(code) == 19 and code.count("-") == 3


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("dis bonjour à Alicia", "bonjour"),
        ("Discute avec Alicia de World of Warcraft", "de world of warcraft"),
        ("demande à alicia comment elle va", "comment elle va"),
        ("salue Alicia", "salut"),
        ("quel objet pour Ashe ?", None),
        ("dis-moi quoi acheter", None),
    ],
)
def test_parse_duo_request(text, topic):
    assert parse_duo_request(text, ["ALICIA"]) == topic


def test_link_sends_sealed_messages_and_ignores_its_own():
    posted = []

    def handler(request):
        posted.append(request.content.decode())
        return httpx.Response(200, json={})

    received = []
    link = DuoLink("code", "moi", "VERIS", received.append, transport=httpx.MockTransport(handler))
    assert link.send("say", text="Coucou", conv="c1", turn=1, max=6)
    assert link.keys.open(posted[0])["text"] == "Coucou"
    link.handle(posted[0])
    assert received == []  # notre propre message
    other = DuoKeys("code").seal(
        {"kind": "say", "sender": "lui", "name": "ALICIA", "ts": int(time.time()), "text": "Yo"}
    )
    link.handle(other)
    assert received[0]["name"] == "ALICIA" and received[0]["text"] == "Yo"
    old = DuoKeys("code").seal({"kind": "say", "sender": "lui", "ts": 0, "text": "vieux"})
    link.handle(old)
    assert len(received) == 1  # message rejoué trop vieux : ignoré


def test_robots_take_turns(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core.ai.providers.fake import FakeModel
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    sent = []

    class Link:
        def send(self, kind, **data):
            sent.append((kind, data))
            return True

        def stop(self):
            pass

    window.duo_link = Link()
    window.voice_box.setChecked(False)  # pas de voix : envoi immédiat
    window._duo_received({"kind": "hello", "name": "VERIS", "sender": "lui"})
    assert window.duo_peer == "VERIS"
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c1", "turn": 1, "max": 3, "text": "Salut !"}
    )
    deadline = time.monotonic() + 5
    while not any(kind == "say" for kind, _ in sent) and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    says = [data for kind, data in sent if kind == "say"]
    assert says and says[0]["turn"] == 2 and says[0]["conv"] == "c1"
    # 3e et dernière réplique de l'autre : on ne répond plus
    window._duo_received(
        {"kind": "say", "name": "VERIS", "conv": "c1", "turn": 3, "max": 3, "text": "Ciao"}
    )
    assert window.duo_conv["ended"]
    # « Veris, dis bonjour à Alicia » passe par le routeur, sans IA
    reply = window.services.analysis.router("dis bonjour à VERIS")
    assert reply.intent == "duo" and reply.text == "bonjour"
    window.duo_link = None
    window.close()
