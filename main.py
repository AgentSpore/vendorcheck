from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
import aiosqlite
from models import VendorCreate, ChecklistAnswers, VendorResponse, EvaluationResponse
from engine import init_db, create_vendor, list_vendors, get_vendor, evaluate_vendor, list_evaluations

DB_PATH = "vendorcheck.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
        await init_db()
    yield


app = FastAPI(title="VendorCheck", version="1.0.0", lifespan=lifespan)


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        yield db


@app.post("/vendors", response_model=VendorResponse, status_code=201)
async def add_vendor(body: VendorCreate, db=Depends(get_db)):
    return await create_vendor(db, body.name, body.vendor_url, body.use_case)


@app.get("/vendors", response_model=list[VendorResponse])
async def get_vendors(db=Depends(get_db)):
    return await list_vendors(db)


@app.get("/vendors/{vendor_id}", response_model=VendorResponse)
async def get_vendor_by_id(vendor_id: int, db=Depends(get_db)):
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor


@app.post("/vendors/{vendor_id}/evaluate", response_model=EvaluationResponse, status_code=201)
async def run_evaluation(vendor_id: int, body: ChecklistAnswers, db=Depends(get_db)):
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return await evaluate_vendor(db, vendor_id, body.model_dump())


@app.get("/vendors/{vendor_id}/evaluations", response_model=list[EvaluationResponse])
async def get_vendor_evaluations(vendor_id: int, db=Depends(get_db)):
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return await list_evaluations(db, vendor_id=vendor_id)


@app.get("/evaluations", response_model=list[EvaluationResponse])
async def get_all_evaluations(db=Depends(get_db)):
    return await list_evaluations(db)
