"""Mémoire courte de conversation, uniquement en RAM."""

from alicia.core.models import ConversationTurn

MAX_HISTORY_TURNS = 4
MAX_HISTORY_CHARACTERS = 6000


class ConversationMemory:
    def __init__(self) -> None:
        self._turns: list[ConversationTurn] = []

    def append(self, question: str, answer: str) -> None:
        if not isinstance(question, str) or not isinstance(answer, str):
            raise ValueError("Un échange doit contenir une question et une réponse textuelles.")
        question, answer = question.strip(), answer.strip()
        if not question or not answer:
            return
        question = question[: MAX_HISTORY_CHARACTERS // 2]
        answer = answer[: MAX_HISTORY_CHARACTERS - len(question)]
        self._turns.append(ConversationTurn(user=question, assistant=answer))
        self._turns = self._turns[-MAX_HISTORY_TURNS:]
        while (
            sum(len(turn.user) + len(turn.assistant) for turn in self._turns)
            > MAX_HISTORY_CHARACTERS
        ):
            self._turns.pop(0)

    def snapshot(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    def clear(self) -> None:
        self._turns.clear()


def bounded_history(history: tuple[ConversationTurn, ...]) -> tuple[ConversationTurn, ...]:
    """Borne aussi les requêtes créées sans passer par la session."""
    memory = ConversationMemory()
    for turn in history[-MAX_HISTORY_TURNS:]:
        if (
            isinstance(turn, ConversationTurn)
            and isinstance(turn.user, str)
            and isinstance(turn.assistant, str)
        ):
            memory.append(turn.user, turn.assistant)
    return memory.snapshot()
