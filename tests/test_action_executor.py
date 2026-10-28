from datetime import UTC, datetime
from threading import Event

import pytest

from alicia.actions.desktop import DesktopActions, DesktopError
from alicia.actions.executor import ActionCancelled, ActionError, ActionExecutor, PreparedAction
from alicia.actions.models import ActionPlan, ActionPlanError
from alicia.actions.notes import NoteError, NoteStore
from alicia.actions.research import ActionResearchError
from alicia.core.models import WebSource
from alicia.research.search import SearchError


class Search:
    def __init__(self, sources=(), error=False):
        self.sources = sources
        self.error = error
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.error:
            raise SearchError("Unavailable")
        return self.sources


class Answerer:
    def summarize(self, query, sources, *, cancelled):
        assert query and sources
        return 'Voici la réponse. <img src=x onerror="alert(1)"> [1]'


def source(url="https://example.com/guide", title="Guide WoW <script>alert(1)</script>"):
    return WebSource(title, url, "Un équipement à comparer & vérifier.", datetime.now(UTC))


def executor(tmp_path, search=None, answerer=None):
    opened = []
    desktop = DesktopActions(browser_opener=lambda url, **kwargs: opened.append(url) or True)
    return ActionExecutor(
        search_provider=search or Search(),
        desktop=desktop,
        notes_directory=tmp_path / "notes",
        answerer=answerer,
    ), opened


def test_prepare_search_has_no_desktop_or_file_side_effect(tmp_path):
    search = Search((source(),))
    engine, opened = executor(tmp_path, search, Answerer())
    prepared = engine.prepare(ActionPlan("search_web", query="stuff war wow forever"))
    assert search.queries == ["stuff war wow forever"]
    assert prepared.answer and not prepared.answer_unavailable
    assert opened == [] and not (tmp_path / "notes").exists()


def test_search_opens_local_answer_page_with_escaped_text_and_real_sources(tmp_path):
    engine, opened = executor(tmp_path, Search((source(),)), Answerer())
    result = engine.execute(
        engine.prepare(ActionPlan("search_web", query="<script>query</script>"))
    )
    assert result.created_path.is_file()
    assert opened == [result.created_path.resolve().as_uri()]
    page = result.created_path.read_text(encoding="utf-8")
    assert "Voici la réponse" in page and "&lt;img" in page
    assert result.text.startswith('Voici la réponse. <img src=x onerror="alert(1)"> [1]')
    assert ">[1] Guide WoW &lt;script&gt;" in page
    assert "&lt;script&gt;" in page and "<script>" not in page
    assert "<img src=x" not in page
    assert "https://example.com/guide" in page
    assert "pages complètes n’ont pas été consultées" in page
    assert "Content-Security-Policy" in page
    assert len(result.sources) == 1 and result.sources[0].url == "https://example.com/guide"


def test_search_model_failure_keeps_sources_without_invented_answer(tmp_path):
    class Unavailable:
        def summarize(self, *args, **kwargs):
            raise ActionResearchError("Unavailable")

    engine, _ = executor(tmp_path, Search((source(),)), Unavailable())
    prepared = engine.prepare(ActionPlan("search_web", query="actualités du jeu"))
    assert prepared.answer_unavailable and prepared.answer == ""
    result = engine.execute(prepared)
    assert "synthèse n’est pas disponible" in result.text
    assert "synthèse de la réponse n’est pas disponible" in result.created_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("error", [True, False])
def test_search_failure_or_empty_results_opens_browser_search_honestly(tmp_path, error):
    engine, opened = executor(tmp_path, Search(error=error))
    result = engine.execute(engine.prepare(ActionPlan("search_web", query="WoW & guides")))
    assert opened == ["https://duckduckgo.com/?q=WoW+%26+guides"]
    assert "ne m’a pas fourni de sources vérifiables" in result.text
    assert result.sources == () and result.created_path is None


def test_unsafe_source_is_not_opened_or_written(tmp_path):
    engine, opened = executor(tmp_path, Search((source(url="file:///etc/passwd"),)))
    result = engine.execute(engine.prepare(ActionPlan("search_web", query="guide")))
    assert opened == ["https://duckduckgo.com/?q=guide"] and result.sources == ()


def test_cancel_between_prepare_and_execute_prevents_all_effects(tmp_path):
    engine, opened = executor(tmp_path)
    prepared = engine.prepare(ActionPlan("create_note", title="Liste", content="À garder"))
    stop = Event()
    stop.set()
    with pytest.raises(ActionCancelled):
        engine.execute(prepared, cancelled=stop.is_set)
    assert not (tmp_path / "notes").exists() and opened == []


def test_cancel_during_search_prevents_late_browser_open(tmp_path):
    stop = Event()

    class Slow:
        def search(self, query):
            stop.set()
            return (source(),)

    engine, opened = executor(tmp_path, Slow())
    with pytest.raises(ActionCancelled):
        engine.prepare(ActionPlan("search_web", query="guide"), cancelled=stop.is_set)
    assert opened == [] and not (tmp_path / "notes").exists()


def test_cancel_after_report_is_saved_prevents_browser_open(tmp_path):
    stop = Event()

    class Store(NoteStore):
        def create_report(self, content, *, cancelled):
            path = super().create_report(content, cancelled=cancelled)
            stop.set()
            return path

    opened = []
    engine = ActionExecutor(
        search_provider=Search((source(),)),
        desktop=DesktopActions(browser_opener=lambda url, **kw: opened.append(url) or True),
        notes=Store(tmp_path / "notes"),
    )
    prepared = engine.prepare(ActionPlan("search_web", query="guide"))
    with pytest.raises(ActionCancelled):
        engine.execute(prepared, cancelled=stop.is_set)
    assert opened == []


def test_note_created_as_utf8_markdown_without_browser_open(tmp_path):
    engine, opened = executor(tmp_path)
    result = engine.execute(
        engine.prepare(
            ActionPlan("create_note", title="Équipement.md", content="# Épée\nÀ vérifier")
        )
    )
    assert result.created_path.suffix == ".md"
    assert result.created_path.read_text(encoding="utf-8") == "# Épée\nÀ vérifier"
    assert list(result.created_path.parent.glob("*.tmp")) == [] and opened == []


def test_existing_name_collision_is_preserved_and_temp_is_cleaned(tmp_path, monkeypatch):
    from alicia.actions import notes

    class Clock:
        @staticmethod
        def now(_zone):
            return datetime(2026, 10, 29, tzinfo=UTC)

    monkeypatch.setattr(notes, "datetime", Clock)
    monkeypatch.setattr(notes.secrets, "token_hex", lambda size: "fixed")
    store = NoteStore(tmp_path / "notes")
    path = store.create_note("Identique", "original")
    with pytest.raises(NoteError):
        store.create_note("Identique", "replacement")
    assert path.read_text() == "original"
    assert sorted(path.name for path in (tmp_path / "notes").iterdir()) == [path.name]


@pytest.mark.parametrize("title", ["../outside", "C:\\outside", "script.bat", "page.html", ".."])
def test_notes_refuse_paths_and_executable_or_html_files(tmp_path, title):
    with pytest.raises(NoteError):
        NoteStore(tmp_path / "notes").create_note(title, "content")
    assert not (tmp_path / "notes").exists()


def test_note_directory_symlink_is_preserved(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    target = tmp_path / "linked"
    try:
        target.symlink_to(original, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(NoteError):
        NoteStore(target).create_note("Note", "content")
    assert target.is_symlink() and list(original.iterdir()) == []


def test_desktop_uses_fixed_quoted_argument_list_and_no_shell(tmp_path):
    system = tmp_path / "Windows root" / "System32"
    system.mkdir(parents=True)
    executable = system / "notepad.exe"
    executable.touch()
    launched = []
    desktop = DesktopActions(
        platform="win32",
        windows_root=system.parent,
        process_factory=lambda arguments, **kwargs: launched.append((arguments, kwargs)),
    )
    assert desktop.open_app("Bloc-notes") == "Bloc-notes"
    assert launched[0][0] == [str(executable)]
    assert launched[0][1]["shell"] is False
    assert all(key in launched[0][1] for key in ("stdin", "stdout", "stderr", "creationflags"))


@pytest.mark.parametrize("app", ["cmd.exe", "powershell", "notepad.exe & whoami", "C:\\evil.exe"])
def test_unknown_application_cannot_reach_process_factory(tmp_path, app):
    launched = []
    desktop = DesktopActions(platform="win32", process_factory=lambda *a, **kw: launched.append(a))
    with pytest.raises(DesktopError):
        desktop.open_app(app)
    assert launched == []


def test_known_folder_passes_one_path_argument_to_explorer(tmp_path):
    windows = tmp_path / "Windows"
    windows.mkdir()
    (windows / "explorer.exe").touch()
    downloads = tmp_path / "Mes téléchargements"
    downloads.mkdir()
    launched = []
    desktop = DesktopActions(
        platform="win32",
        windows_root=windows,
        folder_resolver=lambda name: (
            downloads if name == "downloads" else pytest.fail("Unexpected folder")
        ),
        process_factory=lambda args, **kwargs: launched.append(args),
    )
    assert desktop.open_folder("downloads") == downloads
    assert launched == [[str(windows / "explorer.exe"), str(downloads)]]


def test_unavailable_app_reports_failure_instead_of_claiming_open(tmp_path):
    desktop = DesktopActions(platform="win32", windows_root=tmp_path)
    with pytest.raises(DesktopError, match="pas installée"):
        desktop.open_app("Paint")


def test_browser_failure_is_visible_and_private_urls_rejected():
    desktop = DesktopActions(browser_opener=lambda *a, **kw: False)
    with pytest.raises(DesktopError, match="Aucun navigateur"):
        desktop.open_url("https://example.com/")
    with pytest.raises(ActionPlanError):
        desktop.open_url("http://127.0.0.1/")


def test_no_action_can_be_executed_without_prepare_contract(tmp_path):
    engine, opened = executor(tmp_path)
    with pytest.raises(ActionError):
        engine.execute(ActionPlan("open_url", url="https://example.com/"))
    with pytest.raises(ActionError):
        engine.execute(PreparedAction(ActionPlan("answer")))
    assert opened == []
