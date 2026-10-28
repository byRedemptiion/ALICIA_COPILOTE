from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from alicia.actions.desktop import DesktopActions
from alicia.actions.executor import ActionCancelled, ActionExecutor, ActionResult, PreparedAction
from alicia.actions.models import ActionPlan
from alicia.actions.planner import LocalActionPlanner
from alicia.capture.demo import DemoCapture
from alicia.config import Settings
from alicia.core.models import AnalysisResult, WebSource
from alicia.ui.main_window import MainWindow
from alicia.ui.smoke import wait_until


class CountingCapture(DemoCapture):
    def __init__(self):
        self.count = 0

    def capture(self, source):
        self.count += 1
        return super().capture(source)


class Vision:
    def __init__(self):
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return AnalysisResult("Une réponse sur l’écran.", "test", 0.01, request.frame.capture_id)


class Planner:
    def __init__(self):
        self.plan_result = ActionPlan("open_app", app="calculatrice")
        self.started, self.release = Event(), Event()
        self.release.set()
        self.requests = []

    def plan(self, text, history=()):
        self.requests.append((text, history))
        self.started.set()
        assert self.release.wait(3)
        return self.plan_result


class Executor:
    def __init__(self):
        self.prepared, self.executed = [], []
        self.prepare_started, self.prepare_release = Event(), Event()
        self.execute_started, self.execute_release = Event(), Event()
        self.prepare_release.set()
        self.execute_release.set()

    def prepare(self, plan, *, cancelled):
        self.prepared.append(plan)
        self.prepare_started.set()
        assert self.prepare_release.wait(3)
        # Deliberately simulate a late read-only provider result after Stop.
        return PreparedAction(plan)

    def execute(self, prepared, *, cancelled):
        self.execute_started.set()
        assert self.execute_release.wait(3)
        if cancelled():
            raise ActionCancelled("Demande annulée.")
        self.executed.append(prepared.plan)
        return ActionResult("L’application demandée a été ouverte.")


class Listener:
    def __init__(self, _path, on_text, on_activity, **_kwargs):
        self.on_text, self.on_activity = on_text, on_activity
        self.active = self.paused = False

    def start(self, _device):
        self.active = True
        self.on_activity(True)

    def stop(self):
        self.active, self.paused = False, True

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def set_interruption_mode(self, _enabled):
        pass


@pytest.fixture
def action_window(app, tmp_path, monkeypatch):
    fixtures = []

    def make(*, demo=False):
        capture, vision, planner, executor = CountingCapture(), Vision(), Planner(), Executor()
        window = MainWindow(
            Settings(notes_directory=tmp_path / "notes", capture_interval_ms=10000),
            capture,
            vision,
            demo=demo,
        )
        window.actions.planner, window.actions.executor = planner, executor
        window.conversation.listener_factory = Listener
        speech = []
        monkeypatch.setattr(
            window.speech_provider, "synthesize", lambda text: speech.append(text) or b"wav"
        )

        def play(_audio):
            window.playback._active = True
            window.playback.speaking_changed.emit(True)

        monkeypatch.setattr(window.playback, "play", play)
        window.show()
        wait_until(app, lambda: not window.jobs)
        window.conversation.continuous.setChecked(False)
        fixture = SimpleNamespace(
            window=window,
            capture=capture,
            vision=vision,
            planner=planner,
            executor=executor,
            app=app,
            speech=speech,
        )
        fixtures.append(fixture)
        return fixture

    yield make
    for fixture in fixtures:
        fixture.planner.release.set()
        fixture.executor.prepare_release.set()
        fixture.executor.execute_release.set()
        fixture.window.stop()
        wait_until(app, lambda: not fixture.window.jobs)
        fixture.window.close()
        fixture.window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def send(fixture, text="Ouvre la calculatrice"):
    fixture.window.question.setPlainText(text)
    fixture.window.send_button.click()


def test_typed_action_works_with_observation_stopped_and_no_microphone(action_window):
    fixture = action_window()
    send(fixture)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert len(fixture.executor.executed) == 1
    assert fixture.capture.count == 0
    assert fixture.vision.requests == []
    assert fixture.window.conversation.listener is None
    assert not fixture.window.session.active
    assert fixture.window.response_text == "L’application demandée a été ouverte."
    assert fixture.window.speak_button.isEnabled()
    assert fixture.speech == []


def test_manual_speech_of_typed_result_works_while_observation_stays_stopped(action_window):
    fixture = action_window()
    send(fixture)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    fixture.window.speak_button.click()
    wait_until(fixture.app, lambda: not fixture.window.jobs and fixture.window.playback.active)
    assert fixture.speech == ["L’application demandée a été ouverte."]
    assert fixture.window.conversation.listener is None
    assert not fixture.window.session.active
    assert fixture.window.stop_button.isEnabled()
    fixture.window.stop_button.click()
    assert not fixture.window.playback.active


def test_typed_screen_question_uses_fresh_capture_without_opening_microphone(action_window):
    fixture = action_window()
    fixture.planner.plan_result = ActionPlan("answer")
    fixture.window.start()
    fixture.window.consent.setChecked(True)
    fixture.window.capture(background=True)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    old_frame = fixture.window.session.frame
    send(fixture, "Que contient cet écran ?")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert len(fixture.vision.requests) == 1
    assert fixture.capture.count == 2
    assert fixture.vision.requests[0].frame.capture_id != old_frame.capture_id
    assert fixture.vision.requests[0].question == "Que contient cet écran ?"
    assert fixture.window.conversation.listener is None
    assert fixture.speech == []


def test_typed_question_without_capture_authorization_does_not_observe(action_window):
    fixture = action_window()
    fixture.planner.plan_result = ActionPlan("answer")
    send(fixture, "Que contient cet écran ?")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.capture.count == 0
    assert fixture.vision.requests == []
    assert "lancez l’observation" in fixture.window.answer.toPlainText()


def test_voice_directive_executes_without_capturing_and_reads_result(action_window):
    fixture = action_window()
    fixture.window.start()
    fixture.window.consent.setChecked(True)
    fixture.window.conversation.toggle_listening()
    listener = fixture.window.conversation.listener
    listener.on_text("Alicia, ouvre la calculatrice")
    wait_until(fixture.app, lambda: not fixture.window.jobs and fixture.window.playback.active)
    assert len(fixture.executor.executed) == 1
    assert fixture.capture.count == 0
    assert fixture.vision.requests == []
    assert fixture.speech == ["L’application demandée a été ouverte."]
    assert fixture.window.conversation.interrupting


def test_explicit_search_is_authorized_without_enabling_question_web_option(action_window):
    fixture = action_window()
    fixture.planner.plan_result = ActionPlan("search_web", query="guide de jeu")
    assert not fixture.window.conversation.web.isChecked()
    send(fixture, "Trouve-moi un guide de jeu")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.executor.prepared == [ActionPlan("search_web", query="guide de jeu")]
    assert not fixture.window.conversation.web.isChecked()
    assert fixture.capture.count == 0


@pytest.mark.parametrize("stage", ["plan", "prepare", "execute"])
def test_stop_cancels_late_actions_at_each_stage(action_window, stage):
    fixture = action_window()
    barriers = {
        "plan": (fixture.planner.started, fixture.planner.release),
        "prepare": (fixture.executor.prepare_started, fixture.executor.prepare_release),
        "execute": (fixture.executor.execute_started, fixture.executor.execute_release),
    }
    started, release = barriers[stage]
    release.clear()
    send(fixture)
    wait_until(fixture.app, started.is_set)
    assert fixture.window.stop_button.isEnabled()
    fixture.window.stop_button.click()
    release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.executor.executed == []
    assert fixture.window.answer.toPlainText() == ""
    assert fixture.window.session.memory.snapshot() == ()
    assert fixture.speech == []


def test_withdrawing_capture_permission_cancels_pending_voice_action(action_window):
    fixture = action_window()
    fixture.window.start()
    fixture.window.consent.setChecked(True)
    fixture.window.conversation.toggle_listening()
    fixture.executor.prepare_release.clear()
    fixture.window.conversation.listener.on_text("Alicia, ouvre la calculatrice")
    wait_until(fixture.app, fixture.executor.prepare_started.is_set)
    fixture.window.consent.setChecked(False)
    fixture.executor.prepare_release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.executor.executed == []
    assert fixture.window.conversation.listener is None


def test_demo_never_executes_a_real_action(action_window):
    fixture = action_window(demo=True)
    send(fixture)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.executor.prepared == fixture.executor.executed == []
    assert "désactivées dans la démonstration" in fixture.window.answer.toPlainText()
    assert fixture.window.conversation.listener is None


def test_action_history_keeps_frozen_request_without_logging_its_content(action_window):
    fixture = action_window()
    fixture.executor.prepare_release.clear()
    send(fixture, "Ouvre une application privée")
    wait_until(fixture.app, fixture.executor.prepare_started.is_set)
    fixture.window.question.setPlainText("Texte modifié pendant le traitement")
    fixture.executor.prepare_release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.window.session.memory.snapshot()[0].user == "Ouvre une application privée"
    assert "application privée" not in fixture.window.events.toPlainText()
    assert "L’application demandée a été ouverte" not in fixture.window.events.toPlainText()


def test_real_planner_and_executor_write_requested_note_from_stopped_ui(action_window):
    fixture = action_window()
    fixture.window.actions.planner = LocalActionPlanner(fixture.window.settings)
    fixture.window.actions.executor = ActionExecutor(
        notes_directory=fixture.window.settings.notes_directory
    )
    send(fixture, "note : Penser à préparer les potions pour le raid.")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    files = list(fixture.window.settings.notes_directory.glob("*.txt"))
    assert len(files) == 1
    assert files[0].read_text() == "Penser à préparer les potions pour le raid."
    assert "note est enregistrée" in fixture.window.answer.toPlainText()
    assert str(files[0]) in fixture.window.answer.toPlainText()
    assert str(files[0]) not in fixture.window.events.toPlainText()
    assert fixture.capture.count == 0
    assert fixture.window.conversation.listener is None


def test_real_search_action_renders_answer_sources_and_opens_generated_page(action_window):
    fixture = action_window()
    opened = []
    source = WebSource(
        "Guide du serveur",
        "https://example.org/guide",
        "Cet extrait donne les informations du serveur.",
        datetime(2026, 10, 29, tzinfo=UTC),
    )

    class Search:
        def search(self, query):
            assert query == "un guide de mon serveur"
            return (source,)

    class Answerer:
        def summarize(self, query, sources, *, cancelled):
            assert not cancelled() and sources == (source,)
            return "La recommandation du guide est disponible [1]."

    fixture.window.actions.planner = LocalActionPlanner(fixture.window.settings)
    fixture.window.actions.executor = ActionExecutor(
        notes_directory=fixture.window.settings.notes_directory,
        search_provider=Search(),
        answerer=Answerer(),
        desktop=DesktopActions(browser_opener=lambda url, **kwargs: opened.append(url) or True),
    )
    send(fixture, "cherche un guide de mon serveur")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    reports = list(fixture.window.settings.notes_directory.glob("*.html"))
    assert len(reports) == 1
    assert opened == [reports[0].resolve().as_uri()]
    html = reports[0].read_text()
    assert "La recommandation du guide est disponible [1]." in html
    assert "https://example.org/guide" in html
    assert "Cet extrait donne les informations du serveur." in html
    assert "La recommandation du guide est disponible [1]." in fixture.window.answer.toPlainText()
    assert fixture.capture.count == 0
    assert not fixture.window.conversation.web.isChecked()
    assert "Guide du serveur" in fixture.window.sources.toPlainText()
