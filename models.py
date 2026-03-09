from __future__ import annotations
from pydantic import BaseModel


class VendorCreate(BaseModel):
    name: str
    vendor_url: str | None = None
    use_case: str | None = None   # e.g. "fraud detection", "recommendation engine"


class ChecklistAnswers(BaseModel):
    # Data & Privacy
    data_residency_clear: bool = False       # Is data residency/jurisdiction documented?
    gdpr_compliant: bool = False             # GDPR / CCPA compliance documented?
    no_training_on_your_data: bool = False   # Vendor won't train on your data?
    data_deletion_guaranteed: bool = False   # Data deletion on contract end?
    # SLA & Reliability
    sla_uptime_pct: float | None = None      # Guaranteed uptime % (e.g. 99.9)
    incident_response_hours: int | None = None  # Max incident response time in hours
    # Model Quality
    drift_monitoring_provided: bool = False  # Vendor monitors model drift?
    explainability_available: bool = False   # Predictions are explainable?
    benchmark_results_shared: bool = False   # Performance benchmarks provided?
    # Commercial
    exit_clause_clean: bool = False          # Clean contract exit without penalty?
    pricing_predictable: bool = False        # No usage-based pricing surprises?
    lock_in_risk_low: bool = False           # Can migrate to another vendor easily?
    # Support
    dedicated_support: bool = False          # Dedicated support contact?
    onboarding_provided: bool = False        # Onboarding/integration help included?


class VendorResponse(BaseModel):
    id: int
    name: str
    vendor_url: str | None
    use_case: str | None
    created_at: str


class EvaluationResponse(BaseModel):
    vendor_id: int
    vendor_name: str
    total_score: int          # 0-100
    risk_level: str           # low | medium | high | critical
    passed: int
    failed: int
    critical_fails: list[str]
    recommendations: list[str]
    created_at: str
