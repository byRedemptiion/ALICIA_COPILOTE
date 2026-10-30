"""Overlay OBS : ALICIA en personne sur le stream, via une source « Navigateur ».

Un petit serveur web local (127.0.0.1 seulement, rien n'est ouvert sur Internet) sert :
- ``/overlay`` : la page à ajouter dans OBS (fond transparent) ;
- ``/events`` : le flux d'événements de la page (Server-Sent Events) : état (écoute,
  réflexion, parole), niveau de la voix, sous-titres, gestes ;
- ``/portrait`` : le portrait du personnage choisi ;
- ``/anim/<fichier>`` : les animations de Nova, déposées dans %LOCALAPPDATA%\\Alicia\\overlay.

Options de la page (dans l'adresse) : ``?size=260`` (taille en px), ``&bulle=0`` (sans
sous-titres), ``&roam=1`` (elle se promène dans toute la source : la régler en plein écran).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse

log = logging.getLogger("alicia.stream")

KEEPALIVE_S = 15.0


class OverlayServer:
    def __init__(
        self,
        port: int = 8765,
        page_config: Callable[[], dict] | None = None,  # type: ignore[type-arg]
        portrait: Callable[[], bytes] | None = None,
        anim_dir: Path | None = None,
    ) -> None:
        self.port = port
        self.page_config = page_config or (lambda: {})
        self.portrait = portrait or (lambda: b"")
        self.anim_dir = anim_dir
        self._clients: list[queue.Queue[str | None]] = []
        self._lock = threading.Lock()
        self._last: dict[str, str] = {}  # dernier événement de chaque type, pour les nouveaux
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # --- démarrage ------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/overlay"

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._clients)

    def start(self) -> bool:
        """Démarre le serveur (essaie quelques ports si celui choisi est pris)."""
        if self._server is not None:
            return True
        handler = _make_handler(self)
        for port in range(self.port, self.port + 10):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError:
                continue
            server.daemon_threads = True
            self._server, self.port = server, port
            self._thread = threading.Thread(
                target=server.serve_forever, name="alicia-overlay", daemon=True
            )
            self._thread.start()
            log.info("Overlay OBS prêt : %s", self.url)
            return True
        log.error("Overlay OBS : aucun port libre à partir de %d", self.port)
        return False

    def stop(self) -> None:
        with self._lock:
            for client in self._clients:
                client.put(None)
            self._clients.clear()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            log.info("Overlay OBS arrêté")

    # --- événements -----------------------------------------------------------------------------

    def publish(self, kind: str, **data: object) -> None:
        """Envoie un événement à toutes les pages ouvertes (appelable depuis tout thread)."""
        message = json.dumps({"type": kind, **data}, ensure_ascii=False)
        with self._lock:
            if kind == "text":
                self._last.pop("hide", None)  # nouveau sous-titre : il est de nouveau visible
            if kind not in ("level", "gesture"):  # rejoués pour une page qui se connecte
                self._last.pop(kind, None)
                self._last[kind] = message
            for client in self._clients:
                try:
                    client.put_nowait(message)
                except queue.Full:
                    pass  # page bloquée : on saute ce message plutôt que de ralentir ALICIA

    def _subscribe(self) -> queue.Queue[str | None]:
        client: queue.Queue[str | None] = queue.Queue(maxsize=200)
        with self._lock:
            for message in self._last.values():
                client.put_nowait(message)
            self._clients.append(client)
        return client

    def _unsubscribe(self, client: queue.Queue[str | None]) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def page(self) -> bytes:
        html = resources.files("alicia.assets").joinpath("overlay.html").read_text("utf-8")
        config = json.dumps(self.page_config(), ensure_ascii=False)
        return html.replace("/*CONFIG*/{}", config).encode("utf-8")


def _make_handler(server: OverlayServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401 - silencieux
            log.debug("overlay %s", fmt % args)

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            try:
                if path in ("/", "/overlay"):
                    self._send(server.page(), "text/html; charset=utf-8")
                elif path == "/portrait":
                    data = server.portrait()
                    self._send(data, "image/png", 200 if data else 404)
                elif path.startswith("/anim/"):
                    self._anim(unquote(path.removeprefix("/anim/")))
                elif path == "/events":
                    self._events()
                else:
                    self._send(b"introuvable", "text/plain; charset=utf-8", 404)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _anim(self, name: str) -> None:
            folder = server.anim_dir
            target = (folder / name).resolve() if folder else None
            if (
                folder is None
                or target is None
                or not target.is_file()
                or folder.resolve() not in target.parents
            ):
                self._send(b"introuvable", "text/plain; charset=utf-8", 404)
                return
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(target.read_bytes(), kind)

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            client = server._subscribe()
            log.info("Overlay OBS : page connectée")
            try:
                while True:
                    try:
                        message = client.get(timeout=KEEPALIVE_S)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")  # garde la connexion ouverte
                        self.wfile.flush()
                        continue
                    if message is None:
                        return
                    self.wfile.write(f"data: {message}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                server._unsubscribe(client)
                log.info("Overlay OBS : page déconnectée")

    return Handler
