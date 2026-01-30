from pydantic import BaseModel, Field


class EvaluationMeta(BaseModel):
    title: str = ""
    category: str = ""
    keywords: list[str] = Field(default_factory=list)


class EvaluationScores(BaseModel):
    logic: int = 0
    info_density: int = 0
    expression: int = 0
    total: int = 0


class EvaluationAnalysis(BaseModel):
    main_points: list[str] = Field(default_factory=list)
    key_data: list[str] = Field(default_factory=list)
    sentiment: str = ""


class EvaluationResult(BaseModel):
    meta: EvaluationMeta = Field(default_factory=EvaluationMeta)
    scores: EvaluationScores = Field(default_factory=EvaluationScores)
    analysis: EvaluationAnalysis = Field(default_factory=EvaluationAnalysis)
    summary: str = ""


class EvaluationResponse(BaseModel):
    raw_text: str
    corrected_text: str
    evaluation: EvaluationResult
    processing_time_ms: float
