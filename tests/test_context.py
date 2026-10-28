from dataclasses import FrozenInstanceError, replace

import pytest

from alicia.capture.demo import DemoCapture
from alicia.core.context import ConversationMemory, bounded_history
from alicia.core.models import ConversationTurn
from alicia.core.session import Session


def test_memory_retains_last_four_complete_turns_in_order():
    memory = ConversationMemory()
    for number in range(6):
        memory.append(f"Question {number}", f"Réponse {number}")
    assert memory.snapshot() == tuple(
        ConversationTurn(f"Question {number}", f"Réponse {number}") for number in range(2, 6)
    )


def test_snapshot_remains_immutable_after_new_answers():
    memory = ConversationMemory()
    memory.append("Cette arme est-elle rapide ?", "Oui, sa vitesse affichée est de 8.")
    snapshot = memory.snapshot()
    memory.append("Et celle-ci ?", "Sa vitesse est illisible.")
    assert len(snapshot) == 1
    with pytest.raises(FrozenInstanceError):
        snapshot[0].assistant = "Réponse modifiée"


def test_large_recent_exchange_is_bounded_and_replaces_older_context():
    memory = ConversationMemory()
    memory.append("Ancienne question", "Ancienne réponse")
    memory.append("Nouvelle question " * 1000, "Nouvelle réponse " * 1000)
    snapshot = memory.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].user.startswith("Nouvelle question")
    assert snapshot[0].assistant.startswith("Nouvelle réponse")
    assert sum(len(turn.user) + len(turn.assistant) for turn in snapshot) <= 6000


def test_blank_exchange_does_not_pollute_context():
    memory = ConversationMemory()
    memory.append("Question", "Réponse")
    memory.append("  ", "Réponse sans question")
    memory.append("Question sans réponse", "\n")
    assert memory.snapshot() == (ConversationTurn("Question", "Réponse"),)


def test_invalid_exchange_types_fail_without_echoing_contents():
    memory = ConversationMemory()
    with pytest.raises(ValueError):
        memory.append(None, "Réponse")
    assert memory.snapshot() == ()


def test_capture_updates_keep_context_but_stop_and_source_change_clear_it():
    source = DemoCapture()
    session = Session()
    session.start(source.window)
    session.memory.append("Quel objet est rapide ?", "L’épée est la plus rapide.")
    assert session.accept_frame(session.generation, source.capture(source.window))
    assert len(session.memory.snapshot()) == 1
    session.stop()
    assert session.memory.snapshot() == ()
    session.start(source.window)
    session.memory.append("Nouveau contexte", "Nouvelle réponse")
    session.start(replace(source.window, handle=9))
    assert session.memory.snapshot() == ()


def test_sessions_do_not_share_memory():
    first, second = Session(), Session()
    first.memory.append("Personnage A", "Équipement A")
    assert second.memory.snapshot() == ()


def test_manually_created_history_cannot_bypass_memory_budget():
    history = tuple(
        ConversationTurn(f"Question {number} " + "Q" * 3000, "R" * 6000) for number in range(50)
    )
    result = bounded_history(history)
    assert len(result) <= 4
    assert sum(len(turn.user) + len(turn.assistant) for turn in result) <= 6000
    assert result[-1].user.startswith("Question 49")


def test_malformed_history_turns_are_ignored():
    valid = ConversationTurn("Question", "Réponse")
    assert bounded_history((None, ConversationTurn(12, "Réponse"), valid)) == (valid,)
