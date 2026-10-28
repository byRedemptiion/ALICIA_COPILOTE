from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    process_id: int


@dataclass(frozen=True)
class CapturedFrame:
    png: bytes
    width: int
    height: int
    window: WindowInfo
    captured_at: datetime
    capture_id: str


@dataclass(frozen=True)
class WebSource:
    title: str
    url: str
    snippet: str
    retrieved_at: datetime


@dataclass(frozen=True)
class AnalysisRequest:
    frame: CapturedFrame
    question: str
    web_sources: tuple[WebSource, ...] = ()


@dataclass(frozen=True)
class AnalysisResult:
    text: str
    model: str
    elapsed_seconds: float
    capture_id: str
    web_sources: tuple[WebSource, ...] = ()
