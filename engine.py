import aiosqlite
import json
from datetime import datetime
from collections import Counter

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE,
                UNIQUE(vendor_id, tag)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tags_vendor ON vendor_tags(vendor_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tags_tag ON vendor_tags(tag)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_compliance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                framework TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE,
                UNIQUE(vendor_id, framework)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                author TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)
        await db.commit()


# ── Scoring ───────────────────────────────────────────────────────────────────

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


# ── Vendors CRUD ──────────────────────────────────────────────────────────────

async def create_vendor(db, name: str, vendor_url, use_case) -> dict:
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        "INSERT INTO vendors (name, vendor_url, use_case, created_at) VALUES (?,?,?,?)",
        (name, vendor_url, use_case, now),
    )
    await db.commit()
    return {
        "id": cur.lastrowid, "name": name, "vendor_url": vendor_url,
        "use_case": use_case, "tags": [], "created_at": now,
    }


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
    cur = await db.execute(
        "SELECT id, name, vendor_url, use_case, created_at FROM vendors ORDER BY id DESC"
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        tags = await _get_tags(db, r[0])
        result.append({
            "id": r[0], "name": r[1], "vendor_url": r[2],
            "use_case": r[3], "tags": tags, "created_at": r[4],
        })
    return result


async def get_vendor(db, vendor_id: int):
    cur = await db.execute(
        "SELECT id, name, vendor_url, use_case, created_at FROM vendors WHERE id=?",
        (vendor_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    tags = await _get_tags(db, r[0])
    return {
        "id": r[0], "name": r[1], "vendor_url": r[2],
        "use_case": r[3], "tags": tags, "created_at": r[4],
    }


async def delete_vendor(db, vendor_id: int) -> bool:
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        return False
    await db.execute("DELETE FROM vendor_tags WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM evaluations WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
    await db.commit()
    return True


# ── Tags ──────────────────────────────────────────────────────────────────────

async def _get_tags(db, vendor_id: int) -> list[str]:
    cur = await db.execute(
        "SELECT tag FROM vendor_tags WHERE vendor_id=? ORDER BY tag", (vendor_id,)
    )
    return [r[0] for r in await cur.fetchall()]


async def add_tag(db, vendor_id: int, tag: str) -> list[str]:
    now = datetime.utcnow().isoformat()
    try:
        await db.execute(
            "INSERT INTO vendor_tags (vendor_id, tag, created_at) VALUES (?,?,?)",
            (vendor_id, tag, now),
        )
        await db.commit()
    except Exception:
        pass  # UNIQUE constraint — tag already exists, that's fine
    return await _get_tags(db, vendor_id)


async def remove_tag(db, vendor_id: int, tag: str) -> bool:
    cur = await db.execute(
        "DELETE FROM vendor_tags WHERE vendor_id=? AND tag=?", (vendor_id, tag)
    )
    await db.commit()
    return cur.rowcount > 0


async def list_all_tags(db) -> list[dict]:
    cur = await db.execute(
        """SELECT tag, COUNT(DISTINCT vendor_id) AS cnt
           FROM vendor_tags GROUP BY tag ORDER BY cnt DESC"""
    )
    return [{"tag": r[0], "vendor_count": r[1]} for r in await cur.fetchall()]


async def list_vendors_by_tag(db, tag: str) -> list[dict]:
    cur = await db.execute(
        """SELECT v.id, v.name, v.vendor_url, v.use_case, v.created_at
           FROM vendors v
           JOIN vendor_tags t ON t.vendor_id = v.id
           WHERE t.tag = ?
           ORDER BY v.name""",
        (tag,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        tags = await _get_tags(db, r[0])
        result.append({
            "id": r[0], "name": r[1], "vendor_url": r[2],
            "use_case": r[3], "tags": tags, "created_at": r[4],
        })
    return result


# ── Assessments ───────────────────────────────────────────────────────────────

async def assess_vendor(db, vendor_id: int, answers: dict) -> dict:
    result = _score(answers)
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        """INSERT INTO evaluations
           (vendor_id, answers, total_score, risk_level, passed, failed,
            critical_fails, recommendations, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            vendor_id, json.dumps(answers), result["total_score"],
            result["risk_level"], result["passed"], result["failed"],
            json.dumps(result["critical_fails"]),
            json.dumps(result["recommendations"]), now,
        ),
    )
    await db.commit()
    vendor = await get_vendor(db, vendor_id)
    return {
        "id": cur.lastrowid, "vendor_id": vendor_id,
        "vendor_name": vendor["name"] if vendor else "unknown",
        "total_score": result["total_score"], "risk_level": result["risk_level"],
        "passed": result["passed"], "failed": result["failed"],
        "critical_fails": result["critical_fails"],
        "recommendations": result["recommendations"], "created_at": now,
    }


async def compare_vendors(db, vendor_ids: list[int]) -> list[dict]:
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
                "vendor_id": vid, "vendor_name": vendor["name"],
                "vendor_url": vendor["vendor_url"], "use_case": vendor["use_case"],
                "tags": vendor["tags"],
                "latest_score": row[1], "risk_level": row[2],
                "passed": row[3], "failed": row[4],
                "critical_fails": json.loads(row[5]),
                "top_recommendations": json.loads(row[6])[:3],
                "evaluated_at": row[7],
            })
        else:
            result.append({
                "vendor_id": vid, "vendor_name": vendor["name"],
                "vendor_url": vendor["vendor_url"], "use_case": vendor["use_case"],
                "tags": vendor["tags"],
                "latest_score": None, "risk_level": None,
                "passed": None, "failed": None,
                "critical_fails": [], "top_recommendations": [],
                "evaluated_at": None,
            })
    result.sort(key=lambda x: (x["latest_score"] or -1), reverse=True)
    return result


async def get_vendor_history(db, vendor_id: int) -> dict | None:
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        return None
    cur = await db.execute(
        "SELECT id, total_score, risk_level, created_at FROM evaluations WHERE vendor_id=? ORDER BY id ASC",
        (vendor_id,),
    )
    rows = await cur.fetchall()
    points = []
    prev_score = None
    for r in rows:
        delta = (r[1] - prev_score) if prev_score is not None else None
        points.append({
            "eval_id": r[0], "total_score": r[1],
            "risk_level": r[2], "delta": delta, "created_at": r[3],
        })
        prev_score = r[1]

    scores = [p["total_score"] for p in points]
    if len(scores) >= 2:
        trend = "improving" if scores[-1] > scores[0] else ("declining" if scores[-1] < scores[0] else "stable")
    else:
        trend = "insufficient_data"

    return {
        "vendor_id": vendor_id, "vendor_name": vendor["name"],
        "evaluations": points, "trend": trend,
        "latest_score": scores[-1] if scores else None,
        "best_score": max(scores) if scores else None,
        "worst_score": min(scores) if scores else None,
    }


# ── Evaluations CRUD ─────────────────────────────────────────────────────────

async def delete_evaluation(db, eval_id: int) -> bool:
    cur = await db.execute("DELETE FROM evaluations WHERE id=?", (eval_id,))
    await db.commit()
    return cur.rowcount > 0


async def list_evaluations(db, vendor_id=None) -> list:
    if vendor_id:
        cur = await db.execute(
            """SELECT e.id, e.vendor_id, v.name, e.total_score, e.risk_level,
                      e.passed, e.failed, e.critical_fails, e.recommendations, e.created_at
               FROM evaluations e LEFT JOIN vendors v ON v.id=e.vendor_id
               WHERE e.vendor_id=? ORDER BY e.id DESC""",
            (vendor_id,),
        )
    else:
        cur = await db.execute(
            """SELECT e.id, e.vendor_id, v.name, e.total_score, e.risk_level,
                      e.passed, e.failed, e.critical_fails, e.recommendations, e.created_at
               FROM evaluations e LEFT JOIN vendors v ON v.id=e.vendor_id
               ORDER BY e.id DESC"""
        )
    rows = await cur.fetchall()
    return [
        {
            "id": r[0], "vendor_id": r[1], "vendor_name": r[2] or "unknown",
            "total_score": r[3], "risk_level": r[4],
            "passed": r[5], "failed": r[6],
            "critical_fails": json.loads(r[7]),
            "recommendations": json.loads(r[8]), "created_at": r[9],
        }
        for r in rows
    ]


async def get_evaluation(db, eval_id: int):
    cur = await db.execute(
        """SELECT e.id, e.vendor_id, v.name, e.total_score, e.risk_level,
                  e.passed, e.failed, e.critical_fails, e.recommendations, e.created_at
           FROM evaluations e LEFT JOIN vendors v ON v.id=e.vendor_id WHERE e.id=?""",
        (eval_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "vendor_id": r[1], "vendor_name": r[2] or "unknown",
        "total_score": r[3], "risk_level": r[4],
        "passed": r[5], "failed": r[6],
        "critical_fails": json.loads(r[7]),
        "recommendations": json.loads(r[8]), "created_at": r[9],
    }


async def get_evaluation_stats(db) -> dict:
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
        "total": len(evals), "by_risk": by_risk, "avg_score": avg_score,
        "top_critical_fails": top_critical, "top_recommendations": top_recs,
    }


async def export_evaluations_csv(db) -> str:
    import csv, io
    evals = await list_evaluations(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "vendor_id", "vendor_name", "total_score", "risk_level",
        "passed", "failed", "critical_fails", "recommendations", "created_at",
    ])
    for e in evals:
        writer.writerow([
            e["id"], e["vendor_id"], e["vendor_name"], e["total_score"],
            e["risk_level"], e["passed"], e["failed"],
            "|".join(e["critical_fails"]), "|".join(e["recommendations"]),
            e["created_at"],
        ])
    return buf.getvalue()


# ── Portfolio Risk ────────────────────────────────────────────────────────────

async def get_portfolio_risk(db) -> dict:
    vendors = await list_vendors(db)
    total_vendors = len(vendors)

    # Get latest evaluation per vendor
    cur = await db.execute(
        """SELECT e.vendor_id, e.total_score, e.risk_level, e.critical_fails,
                  v.name
           FROM evaluations e
           JOIN vendors v ON v.id = e.vendor_id
           WHERE e.id IN (
               SELECT MAX(id) FROM evaluations GROUP BY vendor_id
           )
           ORDER BY e.total_score ASC"""
    )
    latest = await cur.fetchall()

    evaluated = len(latest)
    scores = [r[1] for r in latest]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    # Risk distribution
    risk_counts = Counter(r[2] for r in latest)
    distribution = []
    for level in ["critical", "high", "medium", "low"]:
        cnt = risk_counts.get(level, 0)
        distribution.append({
            "level": level,
            "count": cnt,
            "pct": round(cnt / evaluated * 100, 1) if evaluated else 0,
        })

    # Overall risk level
    if risk_counts.get("critical", 0) > 0:
        overall = "critical"
    elif avg_score >= 80:
        overall = "low"
    elif avg_score >= 60:
        overall = "medium"
    elif avg_score >= 40:
        overall = "high"
    else:
        overall = "critical"

    # Critical vendors (risk = critical or high)
    critical_vendors = []
    for r in latest:
        if r[2] in ("critical", "high"):
            critical_vendors.append({
                "vendor_id": r[0], "vendor_name": r[4],
                "score": r[1], "risk_level": r[2],
                "top_fails": json.loads(r[3])[:3],
            })

    # Aggregate checks and recommendations
    all_critical = []
    all_recs = []
    evals = await list_evaluations(db)
    for e in evals:
        all_critical.extend(e["critical_fails"])
        all_recs.extend(e["recommendations"])

    top_checks = [{"check": k, "count": v} for k, v in Counter(all_critical).most_common(5)]
    top_recs = [{"recommendation": k, "count": v} for k, v in Counter(all_recs).most_common(5)]

    return {
        "total_vendors": total_vendors,
        "evaluated_vendors": evaluated,
        "unevaluated_vendors": total_vendors - evaluated,
        "avg_score": avg_score,
        "overall_risk_level": overall,
        "risk_distribution": distribution,
        "critical_vendors": critical_vendors,
        "top_critical_checks": top_checks,
        "top_recommendations": top_recs,
    }


# ── Compliance ───────────────────────────────────────────────────────────────

VALID_FRAMEWORKS = {"gdpr", "soc2", "hipaa", "iso27001", "pci-dss", "ccpa", "fedramp"}
VALID_COMPLIANCE_STATUS = {"pending", "certified", "expired", "in_progress", "not_applicable"}


async def add_compliance(db, vendor_id: int, data: dict) -> dict:
    now = datetime.utcnow().isoformat()
    try:
        cur = await db.execute(
            """INSERT INTO vendor_compliance (vendor_id, framework, status, expires_at, notes, created_at)
               VALUES (?,?,?,?,?,?)""",
            (vendor_id, data["framework"], data.get("status", "pending"),
             data.get("expires_at"), data.get("notes"), now),
        )
        await db.commit()
    except Exception:
        # Update existing
        await db.execute(
            """UPDATE vendor_compliance SET status=?, expires_at=?, notes=?
               WHERE vendor_id=? AND framework=?""",
            (data.get("status", "pending"), data.get("expires_at"), data.get("notes"),
             vendor_id, data["framework"]),
        )
        await db.commit()
        cur2 = await db.execute(
            "SELECT id FROM vendor_compliance WHERE vendor_id=? AND framework=?",
            (vendor_id, data["framework"]),
        )
        row = await cur2.fetchone()
        return await get_compliance_entry(db, row[0]) if row else {}
    return await get_compliance_entry(db, cur.lastrowid)


async def get_compliance_entry(db, entry_id: int) -> dict:
    cur = await db.execute("SELECT * FROM vendor_compliance WHERE id=?", (entry_id,))
    r = await cur.fetchone()
    if not r:
        return {}
    return {
        "id": r[0], "vendor_id": r[1], "framework": r[2], "status": r[3],
        "expires_at": r[4], "notes": r[5], "created_at": r[6],
    }


async def list_compliance(db, vendor_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM vendor_compliance WHERE vendor_id=? ORDER BY framework", (vendor_id,)
    )
    rows = await cur.fetchall()
    return [{"id": r[0], "vendor_id": r[1], "framework": r[2], "status": r[3],
             "expires_at": r[4], "notes": r[5], "created_at": r[6]} for r in rows]


async def remove_compliance(db, vendor_id: int, framework: str) -> bool:
    cur = await db.execute(
        "DELETE FROM vendor_compliance WHERE vendor_id=? AND framework=?", (vendor_id, framework)
    )
    await db.commit()
    return cur.rowcount > 0


# ── Notes ────────────────────────────────────────────────────────────────────

async def add_note(db, vendor_id: int, note: str, author: str | None = None) -> dict:
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        "INSERT INTO vendor_notes (vendor_id, note, author, created_at) VALUES (?,?,?,?)",
        (vendor_id, note, author, now),
    )
    await db.commit()
    return {"id": cur.lastrowid, "vendor_id": vendor_id, "note": note,
            "author": author, "created_at": now}


async def list_notes(db, vendor_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT id, vendor_id, note, author, created_at FROM vendor_notes WHERE vendor_id=? ORDER BY id DESC",
        (vendor_id,),
    )
    rows = await cur.fetchall()
    return [{"id": r[0], "vendor_id": r[1], "note": r[2], "author": r[3], "created_at": r[4]}
            for r in rows]


# ── Risk Trend Alerts ────────────────────────────────────────────────────────

async def get_risk_alerts(db, vendor_id: int, lookback: int = 5) -> dict:
    """Check if vendor risk has degraded over the last N assessments."""
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        return None
    cur = await db.execute(
        "SELECT total_score, risk_level, created_at FROM evaluations WHERE vendor_id=? ORDER BY id DESC LIMIT ?",
        (vendor_id, lookback),
    )
    rows = await cur.fetchall()
    if not rows:
        return {"vendor_id": vendor_id, "vendor_name": vendor["name"],
                "alerts": [], "trend": "no_data", "evaluations_checked": 0}

    scores = [r[0] for r in rows]
    alerts = []

    # Alert 1: Latest score dropped vs previous
    if len(scores) >= 2 and scores[0] < scores[1]:
        drop = scores[1] - scores[0]
        alerts.append({
            "type": "score_drop",
            "severity": "high" if drop >= 15 else "medium",
            "message": f"Score dropped by {drop} points (from {scores[1]} to {scores[0]})",
        })

    # Alert 2: Risk level worsened
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if len(rows) >= 2:
        curr_risk = risk_order.get(rows[0][1], 0)
        prev_risk = risk_order.get(rows[1][1], 0)
        if curr_risk > prev_risk:
            alerts.append({
                "type": "risk_escalation",
                "severity": "high",
                "message": f"Risk level escalated from {rows[1][1]} to {rows[0][1]}",
            })

    # Alert 3: Consecutive declining trend
    if len(scores) >= 3:
        declining = all(scores[i] <= scores[i+1] for i in range(len(scores)-1))
        if declining and scores[0] < scores[-1]:
            alerts.append({
                "type": "declining_trend",
                "severity": "medium",
                "message": f"Score has been declining over last {len(scores)} assessments ({scores[-1]} -> {scores[0]})",
            })

    # Alert 4: Score below threshold
    if scores[0] < 50:
        alerts.append({
            "type": "below_threshold",
            "severity": "critical" if scores[0] < 30 else "high",
            "message": f"Current score ({scores[0]}) is below acceptable threshold (50)",
        })

    # Check expired compliance
    compliance = await list_compliance(db, vendor_id)
    for c in compliance:
        if c["status"] == "expired":
            alerts.append({
                "type": "compliance_expired",
                "severity": "high",
                "message": f"Compliance certification '{c['framework']}' has expired",
            })

    trend = "declining" if len(scores) >= 2 and scores[0] < scores[-1] else (
        "improving" if len(scores) >= 2 and scores[0] > scores[-1] else "stable")

    return {
        "vendor_id": vendor_id, "vendor_name": vendor["name"],
        "current_score": scores[0], "alerts": alerts,
        "trend": trend, "evaluations_checked": len(scores),
    }
