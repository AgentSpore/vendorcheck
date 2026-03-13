from fastapi import FastAPI, Depends, HTTPException, Query
from contextlib import asynccontextmanager
import aiosqlite
from models import (
    VendorCreate, VendorResponse, VendorUpdate,
    ChecklistAnswers, AssessmentResponse, VendorHistory,
    TagAdd, TagListResponse, TagSummary, PortfolioRisk,
    ComplianceCreate, ComplianceResponse,
    NoteCreate, NoteResponse,
    RiskAlertsResponse,
    ContractCreate, ContractResponse, ContractUpdate,
    CategoryStats,
    DependencyCreate, DependencyResponse, CascadeRiskResponse,
    ComplianceCalendarResponse, ComplianceMatrixResponse,
    EvalDiffResponse,
    ContactCreate, ContactResponse, ContactUpdate,
    BulkAssessmentRequest, BulkAssessmentResponse,
)
from engine import (
    init_db, create_vendor, list_vendors, get_vendor,
    list_evaluations, get_evaluation,
    get_evaluation_stats, export_evaluations_csv,
    update_vendor, compare_vendors,
    assess_vendor, get_vendor_history, delete_vendor, delete_evaluation,
    add_tag, remove_tag, list_all_tags, list_vendors_by_tag,
    get_portfolio_risk,
    add_compliance, list_compliance, remove_compliance, VALID_FRAMEWORKS, VALID_COMPLIANCE_STATUS,
    add_note, list_notes, get_risk_alerts,
    get_vendors_due_for_review, VALID_CATEGORIES,
    create_contract, list_contracts, get_contract, update_contract, delete_contract,
    get_expiring_contracts, get_category_stats,
    add_dependency, list_dependencies, remove_dependency, get_dependency_tree,
    get_compliance_calendar, get_compliance_matrix,
    diff_evaluations,
    create_contact, list_contacts, update_contact, delete_contact,
    bulk_assess, export_portfolio_csv,
)
from fastapi.responses import StreamingResponse
from typing import List, Optional

DB_PATH = "vendorcheck.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="VendorCheck",
    description=(
        "AI vendor risk assessment: checklist scoring, compliance tracking, "
        "notes audit trail, risk alerts, portfolio dashboard, vendor categories, "
        "review scheduling, contract tracking with renewal alerts, "
        "vendor dependency chains with cascade risk analysis, "
        "compliance calendar and cross-vendor matrix, assessment diff comparison, "
        "vendor contacts management, bulk assessment, and portfolio CSV export."
    ),
    version="1.8.0",
    lifespan=lifespan,
)


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


# ── Vendors ───────────────────────────────────────────────────────────────────

@app.post("/vendors", response_model=VendorResponse, status_code=201)
async def add_vendor(body: VendorCreate, db=Depends(get_db)):
    try:
        return await create_vendor(db, body.name, body.vendor_url, body.use_case, body.category)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/vendors/compare")
async def compare_vendors_endpoint(
    ids: str = Query(..., description="Comma-separated vendor IDs"),
    db=Depends(get_db),
):
    try:
        vendor_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    if len(vendor_ids) < 2:
        raise HTTPException(400, "Provide at least 2 vendor IDs")
    return await compare_vendors(db, vendor_ids)


@app.get("/vendors/due-for-review")
async def vendors_due_for_review(
    as_of: Optional[str] = Query(None, description="Check date (YYYY-MM-DD, default: today)"),
    db=Depends(get_db),
):
    """List vendors whose next_review_date has passed or is today."""
    return await get_vendors_due_for_review(db, as_of)


@app.get("/vendors/expiring-contracts")
async def expiring_contracts(
    within_days: int = Query(30, ge=1, le=365, description="Days ahead to check"),
    db=Depends(get_db),
):
    """List contracts expiring within N days across all vendors."""
    return await get_expiring_contracts(db, within_days)


@app.get("/vendors", response_model=List[VendorResponse])
async def get_vendors(
    category: Optional[str] = Query(None, description="Filter by category"),
    db=Depends(get_db),
):
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(422, f"Invalid category. Valid: {', '.join(sorted(VALID_CATEGORIES))}")
    return await list_vendors(db, category)


@app.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor_endpoint(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return v


@app.patch("/vendors/{vendor_id}", response_model=VendorResponse)
async def patch_vendor(vendor_id: int, body: VendorUpdate, db=Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    try:
        v = await update_vendor(db, vendor_id, updates)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not v:
        raise HTTPException(404, "Vendor not found")
    return v


@app.delete("/vendors/{vendor_id}", status_code=204)
async def remove_vendor(vendor_id: int, db=Depends(get_db)):
    if not await delete_vendor(db, vendor_id):
        raise HTTPException(404, "Vendor not found")


# ── Assessment ────────────────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/assess", response_model=AssessmentResponse, status_code=201)
async def assess_vendor_endpoint(vendor_id: int, body: ChecklistAnswers, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await assess_vendor(db, vendor_id, body.model_dump())


@app.get("/vendors/{vendor_id}/history", response_model=VendorHistory)
async def vendor_history_endpoint(vendor_id: int, db=Depends(get_db)):
    result = await get_vendor_history(db, vendor_id)
    if not result:
        raise HTTPException(404, "Vendor not found")
    return result


# ── v1.8.0: Bulk Assessment ──────────────────────────────────────────────────

@app.post("/vendors/assess/bulk", response_model=BulkAssessmentResponse, status_code=201)
async def bulk_assess_endpoint(body: BulkAssessmentRequest, db=Depends(get_db)):
    """Assess multiple vendors in one request. Returns combined results and summary."""
    items = [{"vendor_id": i.vendor_id, "answers": i.answers.model_dump()} for i in body.items]
    return await bulk_assess(db, items)


# ── Compliance ────────────────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/compliance", response_model=ComplianceResponse, status_code=201)
async def add_vendor_compliance(vendor_id: int, body: ComplianceCreate, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    if body.framework.lower() not in VALID_FRAMEWORKS:
        raise HTTPException(422, f"Invalid framework. Valid: {', '.join(sorted(VALID_FRAMEWORKS))}")
    if body.status not in VALID_COMPLIANCE_STATUS:
        raise HTTPException(422, f"Invalid status. Valid: {', '.join(sorted(VALID_COMPLIANCE_STATUS))}")
    return await add_compliance(db, vendor_id, body.model_dump())


@app.get("/vendors/{vendor_id}/compliance", response_model=List[ComplianceResponse])
async def get_vendor_compliance(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await list_compliance(db, vendor_id)


@app.delete("/vendors/{vendor_id}/compliance/{framework}", status_code=204)
async def remove_vendor_compliance(vendor_id: int, framework: str, db=Depends(get_db)):
    if not await remove_compliance(db, vendor_id, framework):
        raise HTTPException(404, "Compliance entry not found")


# ── Notes ─────────────────────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/notes", response_model=NoteResponse, status_code=201)
async def add_vendor_note(vendor_id: int, body: NoteCreate, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await add_note(db, vendor_id, body.note, body.author)


@app.get("/vendors/{vendor_id}/notes", response_model=List[NoteResponse])
async def get_vendor_notes(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await list_notes(db, vendor_id)


# ── Risk Alerts ───────────────────────────────────────────────────────────────

@app.get("/vendors/{vendor_id}/risk-alerts", response_model=RiskAlertsResponse)
async def vendor_risk_alerts(
    vendor_id: int,
    lookback: int = Query(5, ge=2, le=20),
    db=Depends(get_db),
):
    result = await get_risk_alerts(db, vendor_id, lookback)
    if result is None:
        raise HTTPException(404, "Vendor not found")
    return result


# ── Contracts ─────────────────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/contracts", response_model=ContractResponse, status_code=201)
async def add_contract(vendor_id: int, body: ContractCreate, db=Depends(get_db)):
    """Track vendor contract details (value, renewal date, auto-renew, type)."""
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    try:
        return await create_contract(db, vendor_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/vendors/{vendor_id}/contracts", response_model=List[ContractResponse])
async def get_contracts(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await list_contracts(db, vendor_id)


@app.patch("/contracts/{contract_id}", response_model=ContractResponse)
async def patch_contract(contract_id: int, body: ContractUpdate, db=Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    try:
        c = await update_contract(db, contract_id, updates)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not c:
        raise HTTPException(404, "Contract not found")
    return c


@app.delete("/contracts/{contract_id}", status_code=204)
async def remove_contract(contract_id: int, db=Depends(get_db)):
    if not await delete_contract(db, contract_id):
        raise HTTPException(404, "Contract not found")


# ── Dependencies (v1.7.0) ────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/dependencies", response_model=DependencyResponse, status_code=201)
async def add_vendor_dependency(vendor_id: int, body: DependencyCreate, db=Depends(get_db)):
    """Add a vendor dependency (supply chain link)."""
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    try:
        return await add_dependency(db, vendor_id, body.depends_on_id, body.dependency_type, body.description)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/vendors/{vendor_id}/dependencies", response_model=List[DependencyResponse])
async def get_vendor_dependencies(vendor_id: int, db=Depends(get_db)):
    """List direct dependencies for a vendor with their risk levels."""
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await list_dependencies(db, vendor_id)


@app.delete("/vendors/{vendor_id}/dependencies/{dep_id}", status_code=204)
async def remove_vendor_dependency(vendor_id: int, dep_id: int, db=Depends(get_db)):
    if not await remove_dependency(db, vendor_id, dep_id):
        raise HTTPException(404, "Dependency not found")


@app.get("/vendors/{vendor_id}/dependency-tree", response_model=CascadeRiskResponse)
async def vendor_dependency_tree(vendor_id: int, db=Depends(get_db)):
    """Full dependency tree with cascade risk analysis."""
    result = await get_dependency_tree(db, vendor_id)
    if not result:
        raise HTTPException(404, "Vendor not found")
    return result


# ── Compliance Calendar & Matrix (v1.7.0) ────────────────────────────────────

@app.get("/compliance/calendar", response_model=ComplianceCalendarResponse)
async def compliance_calendar(
    within_days: int = Query(90, ge=1, le=365, description="Days ahead to check"),
    db=Depends(get_db),
):
    """Cross-vendor compliance expiration calendar with urgency levels."""
    return await get_compliance_calendar(db, within_days)


@app.get("/compliance/matrix", response_model=ComplianceMatrixResponse)
async def compliance_matrix(db=Depends(get_db)):
    """Vendor x framework compliance matrix showing coverage gaps."""
    return await get_compliance_matrix(db)


# ── Assessment Diff (v1.7.0) ─────────────────────────────────────────────────

@app.get("/evaluations/{eval_a}/diff/{eval_b}", response_model=EvalDiffResponse)
async def evaluation_diff(eval_a: int, eval_b: int, db=Depends(get_db)):
    """Compare two evaluations field-by-field. Works across different vendors."""
    result = await diff_evaluations(db, eval_a, eval_b)
    if not result:
        raise HTTPException(404, "One or both evaluations not found")
    return result


# ── v1.8.0: Vendor Contacts ──────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/contacts", response_model=ContactResponse, status_code=201)
async def add_vendor_contact(vendor_id: int, body: ContactCreate, db=Depends(get_db)):
    """Add a contact person for a vendor. Setting is_primary demotes the existing primary."""
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await create_contact(db, vendor_id, body.model_dump())


@app.get("/vendors/{vendor_id}/contacts", response_model=List[ContactResponse])
async def get_vendor_contacts(vendor_id: int, db=Depends(get_db)):
    """List all contacts for a vendor, primary first."""
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return await list_contacts(db, vendor_id)


@app.patch("/contacts/{contact_id}", response_model=ContactResponse)
async def patch_contact(contact_id: int, body: ContactUpdate, db=Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    result = await update_contact(db, contact_id, updates)
    if not result:
        raise HTTPException(404, "Contact not found")
    return result


@app.delete("/contacts/{contact_id}", status_code=204)
async def remove_contact(contact_id: int, db=Depends(get_db)):
    if not await delete_contact(db, contact_id):
        raise HTTPException(404, "Contact not found")


# ── Tags ──────────────────────────────────────────────────────────────────────

@app.post("/vendors/{vendor_id}/tags", response_model=TagListResponse, status_code=201)
async def add_vendor_tag(vendor_id: int, body: TagAdd, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    tags = await add_tag(db, vendor_id, body.tag)
    return {"vendor_id": vendor_id, "tags": tags}


@app.delete("/vendors/{vendor_id}/tags/{tag}", status_code=204)
async def remove_vendor_tag(vendor_id: int, tag: str, db=Depends(get_db)):
    if not await remove_tag(db, vendor_id, tag):
        raise HTTPException(404, "Tag not found on this vendor")


@app.get("/vendors/{vendor_id}/tags", response_model=TagListResponse)
async def get_vendor_tags(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return {"vendor_id": vendor_id, "tags": v["tags"]}


@app.get("/tags", response_model=List[TagSummary])
async def all_tags(db=Depends(get_db)):
    return await list_all_tags(db)


@app.get("/tags/{tag}/vendors", response_model=List[VendorResponse])
async def vendors_by_tag(tag: str, db=Depends(get_db)):
    return await list_vendors_by_tag(db, tag)


# ── Portfolio Risk ────────────────────────────────────────────────────────────

@app.get("/portfolio/risk", response_model=PortfolioRisk)
async def portfolio_risk(db=Depends(get_db)):
    return await get_portfolio_risk(db)


# ── v1.8.0: Portfolio CSV Export ─────────────────────────────────────────────

@app.get("/portfolio/export/csv")
async def portfolio_csv(db=Depends(get_db)):
    """Export full vendor portfolio (vendors, scores, compliance, contracts, contacts) as CSV."""
    data = await export_portfolio_csv(db)
    return StreamingResponse(
        iter([data]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vendor_portfolio.csv"},
    )


# ── Category Stats ────────────────────────────────────────────────────────────

@app.get("/categories/stats", response_model=List[CategoryStats])
async def category_stats(db=Depends(get_db)):
    """Per-category analytics: vendor count, average score, risk distribution."""
    return await get_category_stats(db)


# ── Evaluations ───────────────────────────────────────────────────────────────

@app.get("/evaluations/stats")
async def evaluation_stats(db=Depends(get_db)):
    return await get_evaluation_stats(db)


@app.get("/evaluations/export/csv")
async def evaluations_csv(db=Depends(get_db)):
    data = await export_evaluations_csv(db)
    return StreamingResponse(
        iter([data]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations.csv"},
    )


@app.get("/evaluations")
async def get_evaluations(vendor_id: Optional[int] = None, db=Depends(get_db)):
    return await list_evaluations(db, vendor_id)


@app.get("/evaluations/{eval_id}")
async def get_evaluation_endpoint(eval_id: int, db=Depends(get_db)):
    e = await get_evaluation(db, eval_id)
    if not e:
        raise HTTPException(404, "Evaluation not found")
    return e


@app.delete("/evaluations/{eval_id}", status_code=204)
async def remove_evaluation(eval_id: int, db=Depends(get_db)):
    if not await delete_evaluation(db, eval_id):
        raise HTTPException(404, "Evaluation not found")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.8.0"}
