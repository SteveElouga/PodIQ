from typing import Optional

from pydantic import BaseModel, field_validator

_VALID_CONFIDENCE = {"high", "medium", "low"}


class AnalysisResponse(BaseModel):
    error_type: str
    root_cause: str
    explanation: str
    solution: str
    confidence: str
    is_recurring: bool
    correlated_service: Optional[str] = None
    correlation_explanation: Optional[str] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v: object) -> str:
        if isinstance(v, str) and v in _VALID_CONFIDENCE:
            return v
        return "medium"

    @field_validator("correlated_service", "correlation_explanation", mode="before")
    @classmethod
    def empty_null(cls, v: object) -> Optional[str]:
        if v in (None, "null", ""):
            return None
        return str(v)
