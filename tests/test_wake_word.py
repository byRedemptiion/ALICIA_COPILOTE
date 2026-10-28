import pytest

from alicia.core.wake_word import WakeWordGate


def test_question_after_wake_word_preserves_text_and_ignores_prefix():
    gate = WakeWordGate()
    assert gate.feed("Hé, ALICIA, compare ces épées !") == "compare ces épées !"
    assert not gate.armed


def test_wake_word_alone_arms_next_final_phrase_only():
    gate = WakeWordGate()
    assert gate.feed("Alicia !") is None
    assert gate.armed
    assert gate.feed("Quel objet choisir ?") == "Quel objet choisir ?"
    assert not gate.armed
    assert gate.feed("Et pour les armures ?") is None


@pytest.mark.parametrize(
    "text", ["Alice, compare", "Amicia, compare", "malicia", "Alicias", "Alicia2", "Alicia_test"]
)
def test_similar_names_and_substrings_do_not_activate(text):
    gate = WakeWordGate()
    assert gate.feed(text) is None
    assert not gate.armed


@pytest.mark.parametrize(
    "text", ["ALÍCIA: où aller ?", "Ali\u0301cia, où aller ?", "Alicia\u0301, où aller ?"]
)
def test_accent_and_unicode_normalization_preserves_question(text):
    assert WakeWordGate().feed(text) == "où aller ?"


def test_activation_expires_at_deadline_without_extending_on_empty_input():
    now = [10.0]
    gate = WakeWordGate(clock=lambda: now[0])
    gate.feed("Alicia")
    now[0] = 17.9
    assert gate.feed("  ") is None
    assert gate.armed
    now[0] = 18.0
    assert not gate.armed
    assert gate.feed("Quel objet choisir ?") is None


def test_question_before_deadline_is_accepted():
    now = [0.0]
    gate = WakeWordGate(timeout_seconds=3, clock=lambda: now[0])
    gate.feed("Alicia")
    now[0] = 2.9
    assert gate.feed("Explique cette statistique") == "Explique cette statistique"


def test_reset_cancels_pending_activation():
    gate = WakeWordGate()
    gate.feed("Alicia")
    gate.reset()
    assert not gate.armed
    assert gate.feed("Une conversation ordinaire") is None


def test_empty_or_invalid_transcription_is_ignored():
    gate = WakeWordGate()
    assert gate.feed("") is None
    assert gate.feed(None) is None


def test_custom_word_is_supported():
    assert WakeWordGate(word="Élodie").feed("ELODIE, explique") == "explique"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeouts_are_rejected(timeout):
    with pytest.raises(ValueError, match="délai"):
        WakeWordGate(timeout_seconds=timeout)


@pytest.mark.parametrize("word", ["", " ", "hey Alicia", "Alicia!"])
def test_invalid_wake_words_are_rejected(word):
    with pytest.raises(ValueError, match="activation"):
        WakeWordGate(word=word)
