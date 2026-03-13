from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class VendorCreate(BaseModel):
    name: str
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None
    category: Optional[str] = Field(None, description="Category: ai_ml | cloud | security | analytics | communication | database | devops | fintech | hr_tech | other")


class VendorResponse(BaseModel):
    id: int
    name: str
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    next_review_date: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None
    category: Optional[str] = None
    next_review_date: Optional[str] = Field(None, description="ISO date for next review (YYYY-MM-DD)")


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


# ── Compliance ────────────────────────────────────────────────────────────────

class ComplianceCreate(BaseModel):
    framework: str = Field(..., description="Framework: gdpr | soc2 | hipaa | iso27001 | pci-dss | ccpa | fedramp")
    status: str = Field("pending", description="Status: pending | certified | expired | in_progress | not_applicable")
    expires_at: Optional[str] = Field(None, description="Certification expiry date (ISO)")
    notes: Optional[str] = None


class ComplianceResponse(BaseModel):
    id: int
    vendor_id: int
    framework: str
    status: str
    expires_at: Optional[str]
    notes: Optional[str]
    created_at: str


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)
    author: Optional[str] = Field(None, max_length=100)


class NoteResponse(BaseModel):
    id: int
    vendor_id: int
    note: str
    author: Optional[str]
    created_at: str


# ── Risk Alerts ───────────────────────────────────────────────────────────────

class RiskAlert(BaseModel):
    type: str
    severity: str
    message: str


class RiskAlertsResponse(BaseModel):
    vendor_id: int
    vendor_name: str
    current_score: Optional[int] = None
    alerts: List[RiskAlert]
    trend: str
    evaluations_checked: int


# ── Contracts ─────────────────────────────────────────────────────────────────

class ContractCreate(BaseModel):
    contract_value: float = Field(..., gt=0, description="Contract value in specified currency")
    currency: str = Field("USD", max_length=3, description="ISO 4217 currency code")
    renewal_date: str = Field(..., description="Next renewal date (YYYY-MM-DD)")
    auto_renew: bool = Field(False, description="Whether contract auto-renews")
    contract_type: str = Field("subscription", description="subscription | perpetual | usage_based | enterprise")
    notes: Optional[str] = Field(None, max_length=1000)


class ContractResponse(BaseModel):
    id: int
    vendor_id: int
    contract_value: float
    currency: str
    renewal_date: str
    auto_renew: bool
    contract_type: str
    notes: Optional[str]
    created_at: str


class ContractUpdate(BaseModel):
    contract_value: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = Field(None, max_length=3)
    renewal_date: Optional[str] = None
    auto_renew: Optional[bool] = None
    contract_type: Optional[str] = None
    notes: Optional[str] = None


# ── Category Stats ────────────────────────────────────────────────────────────

class CategoryStats(BaseModel):
    category: str
    vendor_count: int
    avg_score: Optional[float]
    risk_distribution: dict
