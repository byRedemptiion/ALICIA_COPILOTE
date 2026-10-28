import json
import time

from PySide6.QtCore import QEventLoop


def wait_until(app, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("L’interface n’a pas atteint l’état attendu.")
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    app.processEvents()


def run_smoke(app, window, screenshot=None) -> int:
    """Teste le chemin local ; ne remplace pas le fournisseur par une fausse IA."""
    try:
        wait_until(app, lambda: not window.jobs)
        assert window.windows.count() == 1, "La fenêtre de démonstration est absente."
        window.start_button.click()
        assert window.session.active
        window.capture_button.click()
        wait_until(app, lambda: not window.jobs)
        assert window.session.frame is not None, "La capture locale a échoué."
        assert not window.preview.pixmap().isNull(), "Aperçu absent."
        window.question.setPlainText("Quel objet privilégier pour une attaque rapide ?")
        assert not window.analyze_button.isEnabled(), "L’envoi exige un consentement."
        window.consent.setChecked(True)
        assert window.analyze_button.isEnabled()
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(screenshot)), "Impossible d’enregistrer l’aperçu."
        window.stop_button.click()
        assert not window.session.active and window.session.frame is None
        assert not window.analyze_button.isEnabled()
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": ["window_list", "start", "capture", "preview", "consent", "stop"],
                    "api_calls": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (AssertionError, TimeoutError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False))
        return 1
    finally:
        window.stop()
        window.close()
        app.processEvents()
