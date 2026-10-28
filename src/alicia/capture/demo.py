from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from PIL import Image, ImageDraw

from alicia.core.models import CapturedFrame, WindowInfo
from alicia.core.ports import CaptureError


class DemoCapture:
    """Image synthétique locale ; aucun résultat IA simulé."""

    window = WindowInfo(0, "Démonstration — inventaire fictif", 0)

    def list_windows(self) -> list[WindowInfo]:
        return [self.window]

    def capture(self, window: WindowInfo) -> CapturedFrame:
        if window != self.window:
            raise CaptureError("Fenêtre de démonstration inconnue.")
        image = Image.new("RGB", (960, 540), "#111827")
        draw = ImageDraw.Draw(image)
        draw.text(
            (40, 35), "ALICIA / INVENTAIRE FICTIF - DEMONSTRATION", fill="#9be7d8", font_size=24
        )
        for index, (name, stats) in enumerate(
            [
                ("Epee de voyage", "Attaque : 12 | Vitesse : 8"),
                ("Hache de fer", "Attaque : 20 | Vitesse : 3"),
                ("Bouclier leger", "Defense : 15 | Poids : 4"),
            ]
        ):
            top = 110 + index * 115
            draw.rounded_rectangle((40, top, 920, top + 90), radius=12, fill="#243047")
            draw.text((65, top + 15), name, fill="white", font_size=24)
            draw.text((65, top + 52), stats, fill="#c6cddb", font_size=20)
        draw.text(
            (40, 490),
            "Ces donnees sont fictives. Aucun jeu n'est observe.",
            fill="#c6cddb",
            font_size=18,
        )
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return CapturedFrame(buffer.getvalue(), 960, 540, window, datetime.now(UTC), uuid4().hex)
