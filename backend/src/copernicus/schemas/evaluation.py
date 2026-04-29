from pydantic import BaseModel


class EvaluationResult(BaseModel):
    formatted_content: str = ""
    title: str = ""


class EvaluationResponse(BaseModel):
    raw_text: str
    corrected_text: str
    evaluation: EvaluationResult
    processing_time_ms: float
