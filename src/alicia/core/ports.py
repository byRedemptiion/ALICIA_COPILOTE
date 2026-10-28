from typing import Protocol

from alicia.core.models import AnalysisRequest, AnalysisResult, CapturedFrame, WindowInfo


class CaptureError(RuntimeError):
    pass


class UnsupportedPlatformError(CaptureError):
    pass


class AnalysisError(RuntimeError):
    pass


class ConfigurationError(RuntimeError):
    pass


class CaptureSource(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...

    def capture(self, window: WindowInfo) -> CapturedFrame: ...


class VisionProvider(Protocol):
    def analyze(self, request: AnalysisRequest) -> AnalysisResult: ...
