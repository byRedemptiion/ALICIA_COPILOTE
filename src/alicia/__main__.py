import argparse
import multiprocessing
import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Alicia — copilote visuel pour Windows")
    parser.add_argument(
        "--demo", action="store_true", help="Inventaire fictif local, sans capture de jeu"
    )
    parser.add_argument(
        "--smoke-test", action="store_true", help="Vérifier l’interface sans écran ni appel API"
    )
    parser.add_argument(
        "--screenshot", type=Path, help="Enregistrer l’interface de démonstration en PNG"
    )
    parser.add_argument(
        "--prepare-voice",
        action="store_true",
        help="Installer explicitement le modèle français hors ligne",
    )
    parser.add_argument(
        "--prepare-audio",
        action="store_true",
        help="Installer explicitement Kokoro et Whisper pour l’audio local",
    )
    options = parser.parse_args(argv)
    if options.prepare_voice or options.prepare_audio:
        from alicia.audio.ports import SpeechError
        from alicia.config import load_settings
        from alicia.core.ports import ConfigurationError

        if options.demo or options.smoke_test or options.screenshot:
            parser.error("La préparation audio s’utilise seule.")
        try:
            settings = load_settings()
            if options.prepare_audio:
                from alicia.audio.neural_setup import prepare_neural_voice
                from alicia.audio.whisper_setup import prepare_whisper_model

                print("Préparation de la voix neuronale française Kokoro…", flush=True)
                prepare_neural_voice(settings.neural_model_directory)
                print("Préparation de la reconnaissance française Whisper…", flush=True)
                prepare_whisper_model(settings.whisper_model_path)
                print("Modèles audio locaux prêts.")
                return 0
            from alicia.audio.model_setup import prepare_voice_model

            target = prepare_voice_model(settings.voice_model_path)
        except (SpeechError, ConfigurationError, OSError) as error:
            message = (
                str(error)
                if isinstance(error, (SpeechError, ConfigurationError))
                else "Répertoire du modèle inaccessible."
            )
            print("Alicia : " + message, file=sys.stderr)
            return 2
        print(f"Modèle de reconnaissance vocale prêt : {target}")
        return 0
    if options.screenshot and not options.smoke_test:
        parser.error("--screenshot nécessite --smoke-test.")
    if options.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("XDG_STATE_HOME", str(Path.cwd() / ".local-state"))

    from alicia.bootstrap import run

    return run(options)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
