from dataclasses import FrozenInstanceError

import pytest

from alicia.actions.models import (
    ActionPlan,
    ActionPlanError,
    parse_action_plan,
    validate_public_url,
)


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "answer"},
        {"kind": "clarify", "message": "Quelle application ?"},
        {"kind": "search_web", "query": "guide guerrier français"},
        {"kind": "open_url", "url": "https://example.com/guide?q=bonjour#section"},
        {"kind": "open_app", "app": "Calculatrice"},
        {"kind": "open_folder", "folder": "documents"},
        {"kind": "create_note", "content": "Première ligne\nDeuxième ligne ?"},
    ],
)
def test_supported_actions_round_trip_without_extra_parameters(value):
    plan = parse_action_plan(value)
    assert plan.as_dict() == value
    assert ActionPlan.from_dict(plan.as_dict()) == plan


def test_plan_is_immutable_after_validation():
    plan = ActionPlan("open_app", app="Calculatrice")
    with pytest.raises(FrozenInstanceError):
        plan.app = "cmd.exe"


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"kind": "shell", "command": "calc"},
        {"kind": "answer", "query": "A different hidden action"},
        {"kind": "open_app", "app": "Calculatrice", "url": "https://example.com/"},
        {"kind": "open_app", "app": 42},
        {"kind": "open_app", "app": "Calculatrice\ncmd"},
        {"kind": "open_app", "app": "a" * 101},
        {"kind": "search_web", "query": "a" * 501},
        {"kind": "create_note", "content": "\0private"},
        {"kind": "create_note", "content": " "},
        {"kind": "create_note", "title": "Only a title"},
        {"kind": "open_folder", "folder": "../../"},
        {"kind": "open_folder", "folder": "C:\\Windows"},
        {"kind": "clarify"},
        {"kind": "answer", "extra": "ignored by a lax parser"},
    ],
)
def test_invalid_or_cross_action_payload_is_rejected(value):
    with pytest.raises(ActionPlanError):
        parse_action_plan(value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "ms-settings:privacy",
        "https://user:pass@example.com/",
        "http://localhost/",
        "https://printer.local/",
        "https://internal/",
        "https://service.internal/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://2130706433/",
        "https://example.com:8080/",
        "https://example.com/\r\nprivate",
        "https://example.com/%0d%0aHeader:bad",
        "https://example.com/%2525250a",
        "https://example.com\\@127.0.0.1/",
        "https://bad name.example/",
    ],
)
def test_browser_targets_cannot_be_local_actions_or_ambiguous_urls(url):
    with pytest.raises(ActionPlanError):
        validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://html.duckduckgo.com/html/?q=guide",
        "https://example.com",
        "http://example.com:80/",
        "https://fr.wikipedia.org/wiki/Français",
    ],
)
def test_public_browser_pages_are_valid(url):
    assert validate_public_url(url) == url
