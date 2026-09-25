from pydantic import BaseModel


class EvaluationResult(BaseModel):
    formatted_content: str = ""
    title: str = ""
    # 完整性标记：由服务端写入，用于提示纪要是否基于完整文本
    truncated: bool = False
    degraded_chunks: int = 0  # Map 阶段失败、改用原文片段兜底的分块数


class EvaluationResponse(BaseModel):
    raw_text: str
    corrected_text: str
    evaluation: EvaluationResult
    processing_time_ms: float
