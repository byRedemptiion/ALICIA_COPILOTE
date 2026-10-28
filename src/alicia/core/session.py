from dataclasses import dataclass, field

from alicia.core.context import ConversationMemory
from alicia.core.models import AnalysisResult, CapturedFrame, WindowInfo


@dataclass
class Session:
    generation: int = 0
    active: bool = False
    window: WindowInfo | None = None
    frame: CapturedFrame | None = None
    result: AnalysisResult | None = None
    memory: ConversationMemory = field(default_factory=ConversationMemory)

    def start(self, window: WindowInfo) -> None:
        self.stop()
        self.window = window
        self.active = True

    def stop(self) -> None:
        self.generation += 1
        self.active = False
        self.window = None
        self.frame = None
        self.result = None
        self.memory.clear()

    def accept_frame(self, generation: int, frame: CapturedFrame) -> bool:
        if not self.active or generation != self.generation or frame.window != self.window:
            return False
        self.frame = frame
        self.result = None
        return True

    def accept_result(self, generation: int, result: AnalysisResult) -> bool:
        if (
            not self.active
            or generation != self.generation
            or self.frame is None
            or result.capture_id != self.frame.capture_id
        ):
            return False
        self.result = result
        return True
