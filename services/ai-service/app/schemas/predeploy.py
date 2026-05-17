from pydantic import BaseModel, field_validator, model_validator

_VALID_RISK_LEVELS = {"safe", "warning", "block"}
_VALID_SEVERITIES = {"low", "medium", "high", "critical"}


class RiskItem(BaseModel):
    severity: str
    category: str
    description: str
    fix: str

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v: object) -> str:
        if isinstance(v, str) and v in _VALID_SEVERITIES:
            return v
        return "medium"


class ManifestScanResponse(BaseModel):
    risk_level: str
    summary: str
    risks: list[RiskItem] = []

    @field_validator("risk_level", mode="before")
    @classmethod
    def validate_risk_level(cls, v: object) -> str:
        if isinstance(v, str) and v in _VALID_RISK_LEVELS:
            return v
        return "warning"

    @model_validator(mode="after")
    def fix_critical_safe_contradiction(self) -> "ManifestScanResponse":
        # Only override the obvious model error: critical risks can never be "safe"
        if self.risk_level == "safe" and any(
            r.severity == "critical" for r in self.risks
        ):
            self.risk_level = "block"
        return self
