from datetime import UTC, datetime

import httpx
import pytest

from alicia.research.search import DuckDuckGoSearch, SearchError, _public_url, parse_results

HTML_RESULTS = """
<html><body>
<div class="result results_links">
 <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpatch%3Fx%3D1%26y%3D2&amp;rut=ignored">Mise à jour <b>officielle</b> &amp; guide</a></h2>
 <a class="result__snippet" href="https://example.com/patch">Publié récemment : <b>statistiques</b> modifiées.</a>
</div>
<div class="result results_links">
 <h2><a class="result__a" href="https://www.example.org/guide#section">Guide du joueur</a></h2>
 <div class="result__snippet">Conseils et informations à vérifier.</div>
</div>
</body></html>
"""


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def test_parse_realistic_html_and_timestamp_is_retrieval_not_publication():
    now = datetime(2026, 10, 28, tzinfo=UTC)
    sources = parse_results(HTML_RESULTS, retrieved_at=now)
    assert len(sources) == 2
    assert sources[0].title == "Mise à jour officielle & guide"
    assert sources[0].url == "https://example.com/patch?x=1&y=2"
    assert sources[0].snippet == "Publié récemment : statistiques modifiées."
    assert sources[0].retrieved_at == now
    assert sources[1].url == "https://www.example.org/guide"


def test_lite_result_markup_is_supported():
    html = '<table><tr><td><a class="result-link" href="https://example.com/news">News</a></td></tr><tr><td class="result-snippet">Recent summary.</td></tr></table>'
    source = parse_results(html)[0]
    assert source.title == "News"
    assert source.snippet == "Recent summary."


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://localhost/private",
        "http://127.0.0.1/",
        "http://192.168.1.20/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "https://host.local/a",
        "https://user:secret@example.com/",
        "https://example.com:8000/a",
        "https://example.com/\nprivate",
        "http://2130706433/",
        "http://127.000.000.001/",
        "http://0x7f.0.0.1/",
        "http://singlelabel/",
        "https://duckduckgo.com/l/?uddg=javascript%3Aalert%281%29",
        "https://duckduckgo.com/",
    ],
)
def test_non_public_or_unsafe_source_links_are_rejected(url):
    assert _public_url(url) is None


def test_public_ipv6_and_unicode_domain_links_remain_clickable():
    assert _public_url("https://[2606:4700:4700::1111]/news") is not None
    assert _public_url("https://éxample.com/news") is not None


def test_duplicate_links_are_removed_and_results_bounded():
    assert len(parse_results(HTML_RESULTS * 3, maximum=1)) == 1


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html>No results</html>",
        '<form id="challenge-form"></form>',
        '<div class="anomaly-modal">Verify</div>',
    ],
)
def test_empty_and_challenge_responses_are_not_success(html):
    with pytest.raises(SearchError):
        parse_results(html)


def test_only_query_is_sent_no_images_or_credentials(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=HTML_RESULTS
        )

    with client_for(handler) as client:
        sources = DuckDuckGoSearch(client=client).search("  nouvelles   du jeu ")
    assert len(sources) == 2
    assert len(requests) == 1
    assert requests[0].url.host == "html.duckduckgo.com"
    assert requests[0].url.params["q"] == "nouvelles du jeu"
    assert requests[0].method == "GET" and requests[0].content == b""
    assert "authorization" not in requests[0].headers
    assert "nouvelles du jeu" not in caplog.text


@pytest.mark.parametrize("status", [202, 403, 429, 500])
def test_unavailable_engine_is_reported_without_body_or_retry(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="sensitive server details")

    with client_for(handler) as client, pytest.raises(SearchError) as error:
        DuckDuckGoSearch(client=client).search("question")
    assert "sensitive" not in str(error.value)
    assert len(requests) == 1


def test_timeout_is_safe_and_not_retried():
    def handler(request):
        raise httpx.ReadTimeout("private connection details", request=request)

    with client_for(handler) as client, pytest.raises(SearchError, match="temps"):
        DuckDuckGoSearch(client=client).search("question")


def test_engine_redirect_is_followed_but_source_pages_are_never_fetched():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"location": "https://lite.duckduckgo.com/lite/?q=game"}
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML_RESULTS)

    with client_for(handler) as client:
        assert len(DuckDuckGoSearch(client=client).search("question")) == 2
    assert [request.url.host for request in requests] == [
        "html.duckduckgo.com",
        "lite.duckduckgo.com",
    ]


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com/results",
        "http://html.duckduckgo.com/html/",
        "https://user:secret@duckduckgo.com/html/",
        "https://127.0.0.1/",
    ],
)
def test_other_redirects_are_rejected(location):
    with client_for(lambda _: httpx.Response(302, headers={"location": location})) as client:
        with pytest.raises(SearchError, match="redirection"):
            DuckDuckGoSearch(client=client).search("question")


def test_redirect_limit_is_bounded():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://html.duckduckgo.com/html/?q=loop"})

    with client_for(handler) as client, pytest.raises(SearchError):
        DuckDuckGoSearch(client=client).search("question")
    assert len(seen) == 4


def test_response_size_and_content_type_are_bounded():
    for headers, content in [
        ({"content-type": "text/html"}, b"x" * (512 * 1024 + 1)),
        ({"content-type": "application/json"}, b"{}"),
    ]:
        with client_for(lambda _: httpx.Response(200, headers=headers, content=content)) as client:
            with pytest.raises(SearchError):
                DuckDuckGoSearch(client=client).search("question")


@pytest.mark.parametrize("query", ["", "  ", None, "a" * 501])
def test_invalid_question_does_not_make_network_request(query):
    def handler(_):
        pytest.fail("Invalid question must not contact a search engine")

    with client_for(handler) as client, pytest.raises(SearchError):
        DuckDuckGoSearch(client=client).search(query)


@pytest.mark.parametrize("location", ["https://[broken/", "https://duckduckgo.com:bad/html/", ""])
def test_malformed_redirects_have_safe_search_error(location):
    with client_for(lambda _: httpx.Response(302, headers={"location": location})) as client:
        with pytest.raises(SearchError) as error:
            DuckDuckGoSearch(client=client).search("question")
    assert location not in str(error.value) if location else True


@pytest.mark.parametrize("maximum", [0, 6, True, "5"])
def test_invalid_result_limit_is_rejected(maximum):
    with pytest.raises(ValueError):
        parse_results(HTML_RESULTS, maximum=maximum)


def test_unknown_response_charset_does_not_crash():
    with client_for(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=not-real"},
            content=HTML_RESULTS.encode(),
        )
    ) as client:
        assert DuckDuckGoSearch(client=client).search("question")[0].title.startswith("Mise à jour")
