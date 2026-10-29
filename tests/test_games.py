import tomllib

import pytest

from alicia.core.capture.models import WindowInfo
from alicia.games.profiles import load_profiles, resolve_profile
from alicia.games.store import GameDraft, GameStore, normalize_site, slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.Icy-Veins.com/wow-forever/?x=1#top", "icy-veins.com/wow-forever"),
        ("method.gg/wow-forever/", "method.gg/wow-forever"),
        ("  warcraft.wiki.gg ", "warcraft.wiki.gg"),
        ("pas un site", ""),
        ("", ""),
    ],
)
def test_sites_are_normalized(text, expected):
    assert normalize_site(text) == expected


def test_slugify_handles_accents():
    assert slugify("Élden Ring : Nightreign") == "elden-ring-nightreign"


def test_store_adds_a_game_and_reads_it_back(tmp_path):
    store = GameStore(tmp_path / "games.toml")
    key = store.save(
        None,
        GameDraft(
            "Elden Ring",
            ["EldenRing.exe"],
            [],
            ["https://eldenring.wiki.fextralife.com/", "eldenring.wiki.fextralife.com"],
            "Souls-like.",
        ),
    )
    assert key == "elden-ring"
    assert not store.is_builtin(key)
    tomllib.loads((tmp_path / "games.toml").read_text("utf-8"))  # fichier valide
    profile = load_profiles(tmp_path / "games.toml")[key]
    assert profile.sources == ("eldenring.wiki.fextralife.com",)  # doublon retiré
    window = WindowInfo(1, "ELDEN RING", 2, exe_name="eldenring.exe")
    assert resolve_profile(window, profiles=store.profiles).key == key
    store.delete(key)
    assert key not in store.profiles


def test_store_edits_then_restores_a_builtin_game(tmp_path):
    store = GameStore(tmp_path / "games.toml")
    draft = GameDraft.from_profile(store.profiles["wow-forever"])
    draft.sources.insert(0, "wowhead.com/forever")
    store.save("wow-forever", draft)
    assert store.is_modified("wow-forever")
    assert store.profiles["wow-forever"].sources[0] == "wowhead.com/forever"
    store.reset("wow-forever")
    assert not store.is_modified("wow-forever")
    assert store.profiles["wow-forever"].sources[0] == "icy-veins.com/wow-forever"


def test_store_refuses_a_game_without_name(tmp_path):
    with pytest.raises(ValueError):
        GameStore(tmp_path / "games.toml").save(None, GameDraft(" ", [], [], [], ""))


def test_games_tab_lists_games_and_edits_sites(qt_app, tmp_path):
    from alicia.ui.games_page import GameCard, GamesPage

    store = GameStore(tmp_path / "games.toml")
    page = GamesPage(store, active_game=lambda: "wow-forever")
    cards = [
        page.grid.itemAt(i).widget()
        for i in range(page.grid.count())
        if isinstance(page.grid.itemAt(i).widget(), GameCard)
    ]
    assert {c.key for c in cards} >= {"overwatch", "wow-forever"}
    changed = []
    page.games_changed.connect(lambda: changed.append(True))

    page.open_game("wow-forever")
    assert page.currentWidget() is page.detail_page
    page.site_input.setText("https://www.wowhead.com/forever/")
    page._add_site()
    assert page.site_list()[-1] == "wowhead.com/forever"
    page.sites.setCurrentRow(page.sites.count() - 1)
    page._move_site(-1)
    assert page.site_list()[-2] == "wowhead.com/forever"
    page.site_input.setText("n'importe quoi")
    page._add_site()
    assert "non reconnue" in page.site_error.text()
    assert page.save() == "wow-forever"
    assert changed and "wowhead.com/forever" in store.profiles["wow-forever"].sources

    page.open_game(None)  # nouveau jeu
    page.name_input.setText("Hades II")
    page.site_input.setText("hades.fandom.com")
    page._add_site()
    assert page.save() == "hades-ii"
    page.show_list()
    assert page.currentWidget() is page.list_page
