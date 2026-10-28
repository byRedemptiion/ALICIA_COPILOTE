import pytest

from alicia.core.interruption import is_stop_command, speech_contains_stop_command


@pytest.mark.parametrize(
    "text",
    [
        "Alicia stop",
        "ALICIA, STOP !",
        "Alícia… stop.",
        "Alicia, stop s’il te plaît.",
        "Alicia stop s'il vous plaît",
    ],
)
def test_only_addressed_stop_commands_are_accepted(text):
    assert is_stop_command(text)


@pytest.mark.parametrize(
    "text",
    [
        "stop",
        "Alice stop",
        "Amicia stop",
        "malicia stop",
        "Alicia2 stop",
        "Alicia explique le bouton stop",
        "Je peux dire Alicia stop pour t’arrêter",
        "Alicia stop puis explique la carte",
        "",
        None,
    ],
)
def test_ordinary_speech_and_quotes_cannot_interrupt(text):
    assert not is_stop_command(text)


def test_spoken_help_disables_command_listening_to_reduce_self_triggering():
    assert speech_contains_stop_command("Dites « Alicia, stop » pour couper ma voix.")
    assert speech_contains_stop_command("ALÍCIA : STOP.")
    assert not speech_contains_stop_command("Le bouton stop coupe la voix d’Alicia.")
    assert not speech_contains_stop_command("Malicia stop")
    assert not speech_contains_stop_command("")
