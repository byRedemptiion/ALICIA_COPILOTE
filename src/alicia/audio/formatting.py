def spoken_excerpt(text: str, limit: int = 4096) -> str:
    """Les longues réponses restent affichées même si la lecture doit être bornée."""
    if len(text) <= limit:
        return text
    suffix = " La suite de la réponse est affichée à l’écran."
    cut = text[: limit - len(suffix)]
    boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if boundary > len(cut) // 2:
        cut = cut[: boundary + 1]
    else:
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip() + suffix
