from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class VendorCreate(BaseModel):
    name: str
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None


class VendorResponse(BaseModel):
    id: int
    name: str
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None
    tags: List[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None


class ChecklistAnswers(BaseModel):
    data_residency_clear: bool = False
    gdpr_compliant: bool = False
    no_training_on_your_data: bool = False
    data_deletion_guaranteed: bool = False
    drift_monitoring_provided: bool = False
    explainability_available: bool = False
    benchmark_results_shared: bool = False
    exit_clause_clean: bool = False
    pricing_predictable: bool = False
    lock_in_risk_low: bool = False
    dedicated_support: bool = False
    onboarding_provided: bool = False
    sla_uptime_pct: Optional[float] = Field(None, ge=0, le=100)
    incident_response_hours: Optional[int] = Field(None, ge=0)


class EvaluationCreate(BaseModel):
    vendor_id: int
    score: float
    risk_level: str
    passed: List[str] = []
    failed: List[str] = []
    critical_fails: List[str] = []
    recommendations: List[str] = []


class EvaluationResponse(BaseModel):
    id: int
    vendor_id: int
    score: float
    risk_level: str
    passed: List[str]
    failed: List[str]
    critical_fails: List[str]
    recommendations: List[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AssessmentResponse(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    total_score: int
    risk_level: str
    passed: int
    failed: int
    critical_fails: List[str]
    recommendations: List[str]
    created_at: datetime


class HistoryPoint(BaseModel):
    eval_id: int
    total_score: int
    risk_level: str
    delta: Optional[int] = None
    created_at: datetime


class VendorHistory(BaseModel):
    vendor_id: int
    vendor_name: str
    evaluations: List[HistoryPoint]
    trend: str
    latest_score: Optional[int] = None
    best_score: Optional[int] = None
    worst_score: Optional[int] = None


# ── Tags ──────────────────────────────────────────────────────────────────────

class TagAdd(BaseModel):
    tag: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")


class TagListResponse(BaseModel):
    vendor_id: int
    tags: List[str]


class TagSummary(BaseModel):
    tag: str
    vendor_count: int


# ── Portfolio ─────────────────────────────────────────────────────────────────

class RiskBucket(BaseModel):
    level: str
    count: int
    pct: float


class CriticalVendor(BaseModel):
    vendor_id: int
    vendor_name: str
    score: int
    risk_level: str
    top_fails: List[str]


class PortfolioRisk(BaseModel):
    total_vendors: int
    evaluated_vendors: int
    unevaluated_vendors: int
    avg_score: float
    overall_risk_level: str
    risk_distribution: List[RiskBucket]
    critical_vendors: List[CriticalVendor]
    top_critical_checks: List[dict]
    top_recommendations: List[dict]
