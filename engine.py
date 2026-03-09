import aiosqlite
import json
from datetime import datetime

DB_PATH = "vendorcheck.db"

CRITICAL_FIELDS = [
    "gdpr_compliant",
    "no_training_on_your_data",
    "data_deletion_guaranteed",
    "exit_clause_clean",
]

FIELD_WEIGHTS = {
    "data_residency_clear": 5,
    "gdpr_compliant": 10,
    "no_training_on_your_data": 10,
    "data_deletion_guaranteed": 8,
    "drift_monitoring_provided": 7,
    "explainability_available": 7,
    "benchmark_results_shared": 6,
    "exit_clause_clean": 10,
    "pricing_predictable": 8,
    "lock_in_risk_low": 9,
    "dedicated_support": 5,
    "onboarding_provided": 5,
}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vendor_url TEXT,
                use_case TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                answers TEXT NOT NULL,
                total_score INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                passed INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                critical_fails TEXT NOT NULL,
                recommendations TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id)
            )
        """)
        await db.commit()


def _score(answers: dict) -> dict:
    passed = 0
    failed = 0
    critical_fails = []
    recommendations = []
    total = 0
    max_score = sum(FIELD_WEIGHTS.values())

    for field, weight in FIELD_WEIGHTS.items():
        val = answers.get(field, False)
        if val:
            total += weight
            passed += 1
        else:
            failed += 1
            if field in CRITICAL_FIELDS:
                critical_fails.append(field)

    sla = answers.get("sla_uptime_pct")
    if sla and sla >= 99.9:
        total += 8
        max_score += 8
    elif sla and sla >= 99.0:
        total += 4
        max_score += 8
    else:
        max_score += 8
        recommendations.append("Request SLA with >=99.9% uptime commitment")

    ir = answers.get("incident_response_hours")
    if ir is not None and ir <= 4:
        total += 6
        max_score += 6
    elif ir is not None and ir <= 24:
        total += 3
        max_score += 6
    else:
        max_score += 6
        recommendations.append("Negotiate incident response time <=4 hours")

    normalized = round((total / max_score) * 100)

    if not answers.get("gdpr_compliant"):
        recommendations.append("Vendor must provide GDPR DPA before production use")
    if not answers.get("no_training_on_your_data"):
        recommendations.append("Get written guarantee your data won't train their models")
    if not answers.get("exit_clause_clean"):
        recommendations.append("Negotiate clean exit clause and data export SLA")
    if not answers.get("lock_in_risk_low"):
        recommendations.append("Evaluate vendor lock-in; plan data portability strategy")

    if normalized >= 80:
        risk = "low"
    elif normalized >= 60:
        risk = "medium"
    elif normalized >= 40:
        risk = "high"
    else:
        risk = "critical"

    if len(critical_fails) >= 2:
        risk = "critical"

    return {
        "total_score": normalized,
        "risk_level": risk,
        "passed": passed,
        "failed": failed,
        "critical_fails": critical_fails,
        "recommendations": recommendations,
    }


async def create_vendor(db, name: str, vendor_url, use_case) -> dict:
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        "INSERT INTO vendors (name, vendor_url, use_case, created_at) VALUES (?,?,?,?)",
        (name, vendor_url, use_case, now),
    )
    await db.commit()
    return {"id": cur.lastrowid, "name": name, "vendor_url": vendor_url, "use_case": use_case, "created_at": now}


async def list_vendors(db) -> list:
    cur = await db.execute("SELECT id, name, vendor_url, use_case, created_at FROM vendors ORDER BY id DESC")
    rows = await cur.fetchall()
    return [{"id": r[0], "name": r[1], "vendor_url": r[2], "use_case": r[3], "created_at": r[4]} for r in rows]


async def get_vendor(db, vendor_id: int):
    cur = await db.execute("SELECT id, name, vendor_url, use_case, created_at FROM vendors WHERE id=?", (vendor_id,))
    r = await cur.fetchone()
    return {"id": r[0], "name": r[1], "vendor_url": r[2], "use_case": r[3], "created_at": r[4]} if r else None


async def evaluate_vendor(db, vendor_id: int, answers: dict) -> dict:
    from datetime import datetime
    result = _score(answers)
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        """INSERT INTO evaluations
           (vendor_id, answers, total_score, risk_level, passed, failed, critical_fails, recommendations, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            vendor_id,
            json.dumps(answers),
            result["total_score"],
            result["risk_level"],
            result["passed"],
            result["failed"],
            json.dumps(result["critical_fails"]),
            json.dumps(result["recommendations"]),
            now,
        ),
    )
    await db.commit()
    vendor = await get_vendor(db, vendor_id)
    return {
        "id": cur.lastrowid,
        "vendor_id": vendor_id,
        "vendor_name": vendor["name"] if vendor else "unknown",
        **result,
        "created_at": now,
    }


async def list_evaluations(db, vendor_id=None) -> list:
    if vendor_id:
        cur = await db.execute(
            "SELECT id, vendor_id, total_score, risk_level, passed, failed, critical_fails, recommendations, created_at FROM evaluations WHERE vendor_id=? ORDER BY id DESC",
            (vendor_id,),
        )
    else:
        cur = await db.execute(
            "SELECT id, vendor_id, total_score, risk_level, passed, failed, critical_fails, recommendations, created_at FROM evaluations ORDER BY id DESC"
        )
    rows = await cur.fetchall()
    return [
        {
            "id": r[0], "vendor_id": r[1], "total_score": r[2], "risk_level": r[3],
            "passed": r[4], "failed": r[5],
            "critical_fails": json.loads(r[6]), "recommendations": json.loads(r[7]),
            "created_at": r[8],
        }
        for r in rows
    ]
