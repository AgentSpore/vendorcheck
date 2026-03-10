from pydantic import BaseModel, HttpUrl
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
    created_at: datetime

    model_config = {"from_attributes": True}


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    vendor_url: Optional[str] = None
    use_case: Optional[str] = None


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
