from fastapi import FastAPI, Depends, HTTPException, Query
from contextlib import asynccontextmanager
import aiosqlite
from models import (
    VendorCreate, VendorResponse, VendorUpdate,
    ChecklistAnswers, AssessmentResponse, VendorHistory,
    TagAdd, TagListResponse, TagSummary, PortfolioRisk,
)
from engine import (
    init_db, create_vendor, list_vendors, get_vendor,
    list_evaluations, get_evaluation,
    get_evaluation_stats, export_evaluations_csv,
    update_vendor, compare_vendors,
    assess_vendor, get_vendor_history, delete_vendor, delete_evaluation,
    add_tag, remove_tag, list_all_tags, list_vendors_by_tag,
    get_portfolio_risk,
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
    description="AI vendor risk assessment: checklist scoring, compliance tracking, portfolio risk dashboard, tagging.",
    version="1.4.0",
    lifespan=lifespan,
)


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


# ── Vendors ───────────────────────────────────────────────────────────────────

@app.post("/vendors", response_model=VendorResponse, status_code=201)
async def add_vendor(body: VendorCreate, db=Depends(get_db)):
    return await create_vendor(db, body.name, body.vendor_url, body.use_case)


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


@app.get("/vendors", response_model=List[VendorResponse])
async def get_vendors(db=Depends(get_db)):
    return await list_vendors(db)


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
    v = await update_vendor(db, vendor_id, updates)
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
    """Aggregate risk dashboard across all vendors."""
    return await get_portfolio_risk(db)


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
    return {"status": "ok", "version": "1.4.0"}
