"""Diagnostic sans interface : ``alice-diag list-windows | capture | ask | models``.

Pratique pour isoler un problème (capture ou IA) et l'envoyer avec le log.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from alice.core.config import load_settings
from alice.core.errors import AliceError
from alice.core.logging_setup import setup_logging


def _find_window(capture, needle: str):  # type: ignore[no-untyped-def]
    windows = capture.list_windows()
    if needle.isdigit():
        matches = [w for w in windows if w.handle == int(needle)]
    else:
        matches = [w for w in windows if needle.casefold() in w.label.casefold()]
    if not matches:
        raise AliceError(
            f"Aucune fenêtre ne correspond à « {needle} ». Voir : alice-diag list-windows"
        )
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alice-diag")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-windows", help="fenêtres détectées")
    cap = sub.add_parser("capture", help="capture une fenêtre en PNG")
    cap.add_argument("window", help="HWND ou partie du titre / de l'exécutable")
    cap.add_argument("--out", default="capture.png")
    cap.add_argument("--backend", choices=["auto", "wgc", "printwindow"])
    ask = sub.add_parser("ask", help="envoie une image et une question à l'IA")
    ask.add_argument("image")
    ask.add_argument("question")
    sub.add_parser("models", help="modèles Gemini accessibles avec ta clé")
    sub.add_parser("ping", help="question texte minimale à l'IA (sans image) : teste clé et réseau")
    args = parser.parse_args(argv)

    settings = load_settings()
    setup_logging(settings.log_dir, "DEBUG" if args.debug else settings.log_level)

    try:
        if args.command in ("list-windows", "capture"):
            from dataclasses import replace

            from alice.core.capture.service import CaptureService
            from alice.core.capture.win32 import enable_dpi_awareness

            enable_dpi_awareness()
            capture_settings = settings.capture
            if getattr(args, "backend", None):
                capture_settings = replace(capture_settings, backend=args.backend)
            capture = CaptureService.for_windows(capture_settings)
            if args.command == "list-windows":
                for w in capture.list_windows():
                    size = f"{w.rect.width}x{w.rect.height}" if w.rect else "?"
                    full = " plein-écran" if w.fullscreen else ""
                    print(f"{w.handle:>10}  {size:>10}  écran {w.monitor_index}{full}  {w.label}")
                return 0
            frame = capture.capture(_find_window(capture, args.window))
            frame.image.save(args.out)
            print(
                f"OK {frame.width}x{frame.height} via {frame.backend} en {frame.duration_ms} ms -> {args.out}"
            )
            for note in frame.notes:
                print("  ", note)
            return 0

        from alice.core.ai.factory import create_model

        model = create_model(settings.ai)
        if args.command == "models":
            from alice.core.ai.providers.gemini import GeminiModel

            if not isinstance(model, GeminiModel):
                print(
                    f"La commande models concerne Gemini (fournisseur actuel : {model.provider})."
                )
                return 1
            for name in model.list_models():
                print(name)
            return 0

        from alice.core.ai.base import AnalysisRequest
        from alice.core.ai.image_prep import prepare_image
        from alice.core.ai.prompts import build_system_prompt

        if args.command == "ping":
            print(f"Test de {model.provider}/{model.model} (texte seul)...")
            request = AnalysisRequest(
                question="Réponds seulement : OK",
                images=(),
                system_prompt="Réponds très brièvement.",
                max_output_tokens=256,
                temperature=0,
            )
            result = model.analyze(request, on_delta=lambda t: print(t, end="", flush=True))
            print(f"\n[1er mot {result.first_token_ms} ms, total {result.latency_ms} ms]")
            return 0

        image = prepare_image(
            Image.open(Path(args.image)),
            settings.capture.max_image_side,
            settings.capture.jpeg_quality,
        )
        request = AnalysisRequest(
            question=args.question,
            images=(image,),
            system_prompt=build_system_prompt(),
            max_output_tokens=settings.ai.max_output_tokens,
            temperature=settings.ai.temperature,
        )
        result = model.analyze(request, on_delta=lambda t: print(t, end="", flush=True))
        print(
            f"\n\n[{result.provider}/{result.model} — 1er mot {result.first_token_ms} ms, "
            f"total {result.latency_ms} ms, jetons {result.input_tokens}/{result.output_tokens}]"
        )
        return 0
    except AliceError as exc:
        print(f"ERREUR : {exc.user_message}", file=sys.stderr)
        print(f"Détail : {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
