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
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        "INSERT INTO vendors (name, vendor_url, use_case, created_at) VALUES (?,?,?,?)",
        (name, vendor_url, use_case, now),
    )
    await db.commit()
    return {"id": cur.lastrowid, "name": name, "vendor_url": vendor_url, "use_case": use_case, "created_at": now}


async def update_vendor(db, vendor_id: int, updates: dict) -> dict | None:
    allowed = {"name", "vendor_url", "use_case"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return await get_vendor(db, vendor_id)
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [vendor_id]
    cur = await db.execute(f"UPDATE vendors SET {set_clause} WHERE id=?", values)
    await db.commit()
    if cur.rowcount == 0:
        return None
    return await get_vendor(db, vendor_id)


async def list_vendors(db) -> list:
    cur = await db.execute("SELECT id, name, vendor_url, use_case, created_at FROM vendors ORDER BY id DESC")
    rows = await cur.fetchall()
    return [{"id": r[0], "name": r[1], "vendor_url": r[2], "use_case": r[3], "created_at": r[4]} for r in rows]


async def get_vendor(db, vendor_id: int):
    cur = await db.execute("SELECT id, name, vendor_url, use_case, created_at FROM vendors WHERE id=?", (vendor_id,))
    r = await cur.fetchone()
    return {"id": r[0], "name": r[1], "vendor_url": r[2], "use_case": r[3], "created_at": r[4]} if r else None


async def compare_vendors(db, vendor_ids: list[int]) -> list[dict]:
    """Compare vendors side-by-side using their latest evaluation per vendor."""
    result = []
    for vid in vendor_ids:
        vendor = await get_vendor(db, vid)
        if not vendor:
            continue
        cur = await db.execute(
            """SELECT e.id, e.total_score, e.risk_level, e.passed, e.failed,
                      e.critical_fails, e.recommendations, e.created_at
               FROM evaluations e WHERE e.vendor_id=? ORDER BY e.id DESC LIMIT 1""",
            (vid,),
        )
        row = await cur.fetchone()
        if row:
            result.append({
                "vendor_id": vid,
                "vendor_name": vendor["name"],
                "vendor_url": vendor["vendor_url"],
                "use_case": vendor["use_case"],
                "latest_score": row[1],
                "risk_level": row[2],
                "passed": row[3],
                "failed": row[4],
                "critical_fails": json.loads(row[5]),
                "top_recommendations": json.loads(row[6])[:3],
                "evaluated_at": row[7],
            })
        else:
            result.append({
                "vendor_id": vid,
                "vendor_name": vendor["name"],
                "vendor_url": vendor["vendor_url"],
                "use_case": vendor["use_case"],
                "latest_score": None,
                "risk_level": None,
                "passed": None,
                "failed": None,
                "critical_fails": [],
                "top_recommendations": [],
                "evaluated_at": None,
            })
    result.sort(key=lambda x: (x["latest_score"] or -1), reverse=True)
    return result


async def evaluate_vendor(db, vendor_id: int, answers: dict) -> dict:
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
            "SELECT e.id, e.vendor_id, v.name, e.total_score, e.risk_level, e.passed, e.failed, e.critical_fails, e.recommendations, e.created_at FROM evaluations e LEFT JOIN vendors v ON v.id=e.vendor_id WHERE e.vendor_id=? ORDER BY e.id DESC",
            (vendor_id,),
        )
    else:
        cur = await db.execute(
            "SELECT e.id, e.vendor_id, v.name, e.total_score, e.risk_level, e.passed, e.failed, e.critical_fails, e.recommendations, e.created_at FROM evaluations e LEFT JOIN vendors v ON v.id=e.vendor_id ORDER BY e.id DESC"
        )
    rows = await cur.fetchall()
    return [
        {
            "id": r[0], "vendor_id": r[1], "vendor_name": r[2] or "unknown",
            "total_score": r[3], "risk_level": r[4],
            "passed": r[5], "failed": r[6],
            "critical_fails": json.loads(r[7]), "recommendations": json.loads(r[8]),
            "created_at": r[9],
        }
        for r in rows
    ]


async def get_evaluation_stats(db) -> dict:
    from collections import Counter
    evals = await list_evaluations(db)
    if not evals:
        return {
            "total": 0, "by_risk": {}, "avg_score": 0.0,
            "top_critical_fails": [], "top_recommendations": [],
        }
    by_risk = dict(Counter(e["risk_level"] for e in evals))
    avg_score = round(sum(e["total_score"] for e in evals) / len(evals), 1)
    all_critical = [c for e in evals for c in e["critical_fails"]]
    all_recs = [r for e in evals for r in e["recommendations"]]
    top_critical = [{"check": k, "count": v} for k, v in Counter(all_critical).most_common(5)]
    top_recs = [{"recommendation": k, "count": v} for k, v in Counter(all_recs).most_common(5)]
    return {
        "total": len(evals),
        "by_risk": by_risk,
        "avg_score": avg_score,
        "top_critical_fails": top_critical,
        "top_recommendations": top_recs,
    }


async def export_evaluations_csv(db) -> str:
    import csv
    import io
    evals = await list_evaluations(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "vendor_id", "vendor_name", "total_score", "risk_level",
        "passed", "failed", "critical_fails", "recommendations", "created_at",
    ])
    for e in evals:
        writer.writerow([
            e["id"], e["vendor_id"], e["vendor_name"], e["total_score"], e["risk_level"],
            e["passed"], e["failed"],
            "|".join(e["critical_fails"]),
            "|".join(e["recommendations"]),
            e["created_at"],
        ])
    return buf.getvalue()
