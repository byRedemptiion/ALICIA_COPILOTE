"""Bounded, explicit web searches without API keys or source-page fetching."""

from __future__ import annotations

import ipaddress
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx

from alicia.core.models import WebSource

logger = logging.getLogger("alicia.research")
_ENDPOINT = "https://html.duckduckgo.com/html/"
_ENGINE_HOSTS = {
    "duckduckgo.com",
    "www.duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
}
_MAX_BODY_BYTES = 512 * 1024
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_CHALLENGE_MARKERS = ("anomaly-modal", "challenge-form", "anomaly.js", "bots use duckduckgo too")


class SearchError(RuntimeError):
    """A safe search error suitable for the desktop interface."""


def _clean_text(parts: list[str], maximum: int) -> str:
    return " ".join(" ".join(parts).split())[:maximum]


def _public_url(value: str) -> str | None:
    """Reject obvious private targets; source links are never requested here."""
    if not value or any(ord(character) < 33 or ord(character) == 127 for character in value):
        return None
    try:
        parsed = urlsplit(urljoin(_ENDPOINT, value))
        if parsed.hostname in _ENGINE_HOSTS and parsed.path.rstrip("/") == "/l":
            value = parse_qs(parsed.query, max_num_fields=30).get("uddg", [""])[0]
            if not value or any(ord(character) < 33 for character in value):
                return None
            parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
        ):
            return None
        host = host.rstrip(".").lower()
        if host in _ENGINE_HOSTS:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (
                "." not in host
                or host.endswith(
                    (
                        ".localhost",
                        ".local",
                        ".localdomain",
                        ".internal",
                        ".home",
                        ".home.arpa",
                        ".lan",
                    )
                )
                or re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host)
            ):
                return None
            ascii_host = host.encode("idna").decode("ascii")
            if len(ascii_host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in ascii_host.split(".")
            ):
                return None
        else:
            if not address.is_global:
                return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (TypeError, ValueError, UnicodeError):
        return None


@dataclass
class _Candidate:
    href: str
    title_parts: list[str] = field(default_factory=list)
    snippet_parts: list[str] = field(default_factory=list)


class _ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.candidates: list[_Candidate] = []
        self.current: _Candidate | None = None
        self.title_depth: int | None = None
        self.snippet_depth: int | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag not in _VOID_TAGS:
            self.stack.append(tag)
        if tag == "a" and classes.intersection({"result__a", "result-link"}):
            if len(self.candidates) >= 100:
                return
            self.current = _Candidate(attributes.get("href") or "")
            self.candidates.append(self.current)
            self.title_depth = len(self.stack)
            self.snippet_depth = None
        elif self.current and classes.intersection({"result__snippet", "result-snippet"}):
            self.snippet_depth = len(self.stack)

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.title_depth is not None and depth <= self.title_depth:
            self.title_depth = None
        if self.snippet_depth is not None and depth <= self.snippet_depth:
            self.snippet_depth = None
        del self.stack[depth - 1 :]

    def handle_data(self, data):
        if self.current is not None:
            if self.title_depth is not None:
                self.current.title_parts.append(data)
            if self.snippet_depth is not None:
                self.current.snippet_parts.append(data)


def parse_results(
    html: str, maximum: int = 5, retrieved_at: datetime | None = None
) -> tuple[WebSource, ...]:
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 5:
        raise ValueError("Le nombre de sources doit être compris entre 1 et 5.")
    if any(marker in html.casefold() for marker in _CHALLENGE_MARKERS):
        raise SearchError(
            "Le moteur de recherche demande une vérification. Réessayez plus tard ou ouvrez votre navigateur."
        )
    parser = _ResultParser()
    parser.feed(html)
    parser.close()
    sources: list[WebSource] = []
    seen: set[str] = set()
    retrieved_at = retrieved_at or datetime.now(UTC)
    for candidate in parser.candidates:
        url = _public_url(candidate.href)
        title = _clean_text(candidate.title_parts, 200)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        sources.append(
            WebSource(
                title=title,
                url=url,
                snippet=_clean_text(candidate.snippet_parts, 900),
                retrieved_at=retrieved_at,
            )
        )
        if len(sources) >= maximum:
            break
    if not sources:
        raise SearchError(
            "Aucune source web exploitable n’a été trouvée. Reformulez la question ou réessayez plus tard."
        )
    return tuple(sources)


class DuckDuckGoSearch:
    def __init__(
        self, max_results: int = 5, timeout_seconds: float = 10, client: httpx.Client | None = None
    ):
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= 5
        ):
            raise ValueError("Le nombre de sources doit être compris entre 1 et 5.")
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 30:
            raise ValueError("Le délai de recherche doit être compris entre 1 et 30 secondes.")
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self._client = client

    def search(self, query: str) -> tuple[WebSource, ...]:
        if not isinstance(query, str) or not query.strip():
            raise SearchError("Saisissez une question pour lancer la recherche web.")
        query = " ".join(query.split())
        if len(query) > 500:
            raise SearchError("La question de recherche dépasse 500 caractères ; raccourcissez-la.")
        logger.info("web_search_started")
        client = self._client or httpx.Client(trust_env=True, follow_redirects=False)
        try:
            html = self._request_html(client, query)
        except httpx.TimeoutException:
            raise SearchError(
                "Le moteur de recherche met trop de temps à répondre. Réessayez plus tard."
            ) from None
        except httpx.HTTPError:
            raise SearchError(
                "La recherche web est inaccessible. Vérifiez votre connexion ou réessayez plus tard."
            ) from None
        finally:
            if self._client is None:
                client.close()
        sources = parse_results(html, self.max_results)
        logger.info("web_search_completed source_count=%s", len(sources))
        return sources

    def _request_html(self, client: httpx.Client, query: str) -> str:
        url = _ENDPOINT
        params = {"q": query}
        deadline = time.monotonic() + self.timeout_seconds
        for attempt in range(4):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SearchError("Le délai maximal de recherche est dépassé. Réessayez plus tard.")
            with client.stream(
                "GET",
                url,
                params=params,
                timeout=remaining,
                headers={
                    "User-Agent": "Alicia/0.2 (local game copilot)",
                    "Accept": "text/html",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                },
                follow_redirects=False,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    try:
                        location = response.headers.get("location", "")
                        target = urljoin(str(response.url), location)
                        parsed = urlsplit(target)
                        allowed = (
                            bool(location)
                            and attempt < 3
                            and parsed.scheme == "https"
                            and parsed.hostname in _ENGINE_HOSTS
                            and parsed.username is None
                            and parsed.password is None
                            and parsed.port in {None, 443}
                        )
                    except ValueError:
                        allowed = False
                    if not allowed:
                        raise SearchError(
                            "Le moteur a demandé une redirection non prise en charge. Aucune source n’a été consultée."
                        )
                    url, params = target, None
                    continue
                if response.status_code in {202, 403, 429}:
                    raise SearchError(
                        "Le moteur limite la recherche ou demande une vérification. Réessayez plus tard."
                    )
                if response.status_code != 200:
                    raise SearchError("Le moteur de recherche est momentanément indisponible.")
                if "text/html" not in response.headers.get("content-type", "").casefold():
                    raise SearchError(
                        "Le moteur n’a pas renvoyé une page de résultats exploitable."
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise SearchError(
                            "Le délai maximal de recherche est dépassé. Réessayez plus tard."
                        )
                    body.extend(chunk)
                    if len(body) > _MAX_BODY_BYTES:
                        raise SearchError(
                            "La réponse du moteur est trop volumineuse ; aucune source n’a été retenue."
                        )
                try:
                    return bytes(body).decode(response.encoding or "utf-8", errors="replace")
                except LookupError:
                    return bytes(body).decode("utf-8", errors="replace")
        raise SearchError("La recherche web n’a pas abouti.")
