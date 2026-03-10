from fastapi import FastAPI, Depends, HTTPException, Query
from contextlib import asynccontextmanager
import aiosqlite, json
from models import VendorCreate, VendorResponse, VendorUpdate, EvaluationCreate, EvaluationResponse
from engine import (
    init_db, create_vendor, list_vendors, get_vendor,
    create_evaluation, list_evaluations, get_evaluation,
    get_evaluation_stats, export_evaluations_csv,
    update_vendor, compare_vendors
)
from fastapi.responses import StreamingResponse
from typing import List, Optional

DB_PATH = "vendorcheck.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
        await init_db(db)
    yield

app = FastAPI(title="VendorCheck API", version="1.2.0", lifespan=lifespan)

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


@app.post("/vendors", response_model=VendorResponse, status_code=201)
async def add_vendor(body: VendorCreate, db=Depends(get_db)):
    return await create_vendor(db, body)


# compare BEFORE /{vendor_id} to avoid route conflict
@app.get("/vendors/compare")
async def compare_vendors_endpoint(
    ids: str = Query(..., description="Comma-separated vendor IDs"),
    db=Depends(get_db)
):
    try:
        vendor_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers")
    if len(vendor_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 vendor IDs to compare")
    return await compare_vendors(db, vendor_ids)


@app.get("/vendors", response_model=List[VendorResponse])
async def get_vendors(db=Depends(get_db)):
    return await list_vendors(db)


@app.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor_endpoint(vendor_id: int, db=Depends(get_db)):
    v = await get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


@app.patch("/vendors/{vendor_id}", response_model=VendorResponse)
async def patch_vendor(vendor_id: int, body: VendorUpdate, db=Depends(get_db)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    v = await update_vendor(db, vendor_id, updates)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


@app.post("/evaluations", response_model=EvaluationResponse, status_code=201)
async def add_evaluation(body: EvaluationCreate, db=Depends(get_db)):
    return await create_evaluation(db, body)


# stats and export BEFORE /{eval_id} to avoid route conflict
@app.get("/evaluations/stats")
async def evaluation_stats(db=Depends(get_db)):
    return await get_evaluation_stats(db)


@app.get("/evaluations/export/csv")
async def evaluations_csv(db=Depends(get_db)):
    data = await export_evaluations_csv(db)
    return StreamingResponse(iter([data]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations.csv"})


@app.get("/evaluations", response_model=List[EvaluationResponse])
async def get_evaluations(vendor_id: Optional[int] = None, db=Depends(get_db)):
    return await list_evaluations(db, vendor_id)


@app.get("/evaluations/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation_endpoint(eval_id: int, db=Depends(get_db)):
    e = await get_evaluation(db, eval_id)
    if not e:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return e
