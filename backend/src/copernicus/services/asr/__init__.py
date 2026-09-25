"""语音识别服务包。对外只暴露服务类与数据结构。"""

from copernicus.services.asr.service import ASRService
from copernicus.services.asr.types import ASRResult, Segment, SubSentence

__all__ = ["ASRResult", "ASRService", "Segment", "SubSentence"]
