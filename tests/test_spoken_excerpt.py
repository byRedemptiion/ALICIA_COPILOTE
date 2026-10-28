from alicia.audio.formatting import spoken_excerpt


def test_short_answer_is_spoken_unchanged():
    assert spoken_excerpt("Voici la réponse [1].") == "Voici la réponse [1]."


def test_long_answer_announces_visible_remainder_within_engine_limit():
    original = "Une phrase utile. " * 400
    spoken = spoken_excerpt(original)
    assert len(spoken) <= 4096
    assert spoken.endswith("La suite de la réponse est affichée à l’écran.")
    assert original.startswith(spoken.split(" La suite de la réponse")[0])


def test_long_unbroken_token_stays_within_engine_limit():
    assert len(spoken_excerpt("x" * 8000)) <= 4096
