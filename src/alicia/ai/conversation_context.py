from alicia.core.context import bounded_history
from alicia.core.models import ConversationTurn


def conversation_messages(history: tuple[ConversationTurn, ...]) -> list[dict[str, str]]:
    messages = []
    for turn in bounded_history(history):
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.assistant})
    return messages
