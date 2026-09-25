from typing import Literal

from pydantic import BaseModel

# ok：全部成功；partial：部分分块失败（结果可能不全）；failed：提取失败；skipped：未启用或没有转写可用
StructureStatus = Literal["ok", "partial", "failed", "skipped"]


class ActionItem(BaseModel):
    task: str
    owner: str = ""
    due: str = ""
    timestamp_ms: int | None = None  # 在转写中定位到的位置；None 表示没能定位


class Decision(BaseModel):
    content: str
    timestamp_ms: int | None = None


class EvaluationResult(BaseModel):
    formatted_content: str = ""
    title: str = ""
    # 完整性标记：由服务端写入，用于提示纪要是否基于完整文本
    truncated: bool = False
    degraded_chunks: int = 0  # Map 阶段失败、改用原文片段兜底的分块数
    # 结构化内容：由单独的提取步骤生成，可回溯到转写时间点（旧数据无这些字段）
    action_items: list[ActionItem] = []
    decisions: list[Decision] = []
    structure_status: StructureStatus = "skipped"


class EvaluationResponse(BaseModel):
    raw_text: str
    corrected_text: str
    evaluation: EvaluationResult
    processing_time_ms: float
