import aiosqlite
import json
from datetime import datetime, timedelta
from collections import Counter

DB_PATH = "vendorcheck.db"

VALID_CATEGORIES = {
    "ai_ml", "cloud", "security", "analytics", "communication",
    "database", "devops", "fintech", "hr_tech", "other",
}

VALID_CONTRACT_TYPES = {"subscription", "perpetual", "usage_based", "enterprise"}

VALID_DEPENDENCY_TYPES = {"critical", "important", "optional"}

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
                category TEXT,
                next_review_date TEXT,
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                contract_value REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                renewal_date TEXT NOT NULL,
                auto_renew INTEGER NOT NULL DEFAULT 0,
                contract_type TEXT NOT NULL DEFAULT 'subscription',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_vendor ON vendor_contracts(vendor_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_renewal ON vendor_contracts(renewal_date)"
        )

        # -- v1.7.0: vendor dependencies table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                depends_on_id INTEGER NOT NULL,
                dependency_type TEXT NOT NULL DEFAULT 'important',
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_id) REFERENCES vendors(id) ON DELETE CASCADE,
                UNIQUE(vendor_id, depends_on_id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_deps_vendor ON vendor_dependencies(vendor_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_deps_target ON vendor_dependencies(depends_on_id)"
        )

        # -- v1.8.0: vendor contacts table --
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vendor_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                role TEXT,
                phone TEXT,
                is_primary INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_contacts_vendor ON vendor_contacts(vendor_id)"
        )

        # migrate: add category and next_review_date columns if missing
        cols = await db.execute("PRAGMA table_info(vendors)")
        col_names = {r[1] for r in await cols.fetchall()}
        if "category" not in col_names:
            await db.execute("ALTER TABLE vendors ADD COLUMN category TEXT")
        if "next_review_date" not in col_names:
            await db.execute("ALTER TABLE vendors ADD COLUMN next_review_date TEXT")

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

async def create_vendor(db, name: str, vendor_url, use_case, category=None) -> dict:
    now = datetime.utcnow().isoformat()
    if category and category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category. Valid: {', '.join(sorted(VALID_CATEGORIES))}")
    cur = await db.execute(
        "INSERT INTO vendors (name, vendor_url, use_case, category, created_at) VALUES (?,?,?,?,?)",
        (name, vendor_url, use_case, category, now),
    )
    await db.commit()
    return {
        "id": cur.lastrowid, "name": name, "vendor_url": vendor_url,
        "use_case": use_case, "category": category, "tags": [],
        "next_review_date": None, "created_at": now,
    }


async def update_vendor(db, vendor_id: int, updates: dict) -> dict | None:
    allowed = {"name", "vendor_url", "use_case", "category", "next_review_date"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return await get_vendor(db, vendor_id)
    if "category" in fields and fields["category"] is not None:
        if fields["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category. Valid: {', '.join(sorted(VALID_CATEGORIES))}")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [vendor_id]
    cur = await db.execute(f"UPDATE vendors SET {set_clause} WHERE id=?", values)
    await db.commit()
    if cur.rowcount == 0:
        return None
    return await get_vendor(db, vendor_id)


async def list_vendors(db, category: str | None = None) -> list:
    q = "SELECT id, name, vendor_url, use_case, category, next_review_date, created_at FROM vendors WHERE 1=1"
    params = []
    if category:
        q += " AND category = ?"
        params.append(category)
    q += " ORDER BY id DESC"
    cur = await db.execute(q, params)
    rows = await cur.fetchall()
    result = []
    for r in rows:
        tags = await _get_tags(db, r[0])
        result.append({
            "id": r[0], "name": r[1], "vendor_url": r[2],
            "use_case": r[3], "category": r[4], "tags": tags,
            "next_review_date": r[5], "created_at": r[6],
        })
    return result


async def get_vendor(db, vendor_id: int):
    cur = await db.execute(
        "SELECT id, name, vendor_url, use_case, category, next_review_date, created_at FROM vendors WHERE id=?",
        (vendor_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    tags = await _get_tags(db, r[0])
    return {
        "id": r[0], "name": r[1], "vendor_url": r[2],
        "use_case": r[3], "category": r[4], "tags": tags,
        "next_review_date": r[5], "created_at": r[6],
    }


async def delete_vendor(db, vendor_id: int) -> bool:
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        return False
    await db.execute("DELETE FROM vendor_tags WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM evaluations WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendor_compliance WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendor_notes WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendor_contracts WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendor_dependencies WHERE vendor_id=? OR depends_on_id=?", (vendor_id, vendor_id))
    await db.execute("DELETE FROM vendor_contacts WHERE vendor_id=?", (vendor_id,))
    await db.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
    await db.commit()
    return True


# ── Review Scheduling ─────────────────────────────────────────────────────────

async def get_vendors_due_for_review(db, as_of: str | None = None) -> list[dict]:
    """Return vendors whose next_review_date <= as_of (default: today)."""
    if not as_of:
        as_of = datetime.utcnow().strftime("%Y-%m-%d")
    cur = await db.execute(
        """SELECT id, name, vendor_url, use_case, category, next_review_date, created_at
           FROM vendors
           WHERE next_review_date IS NOT NULL AND next_review_date <= ?
           ORDER BY next_review_date ASC""",
        (as_of,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        tags = await _get_tags(db, r[0])
        days_overdue = (datetime.strptime(as_of, "%Y-%m-%d") - datetime.strptime(r[5], "%Y-%m-%d")).days
        result.append({
            "id": r[0], "name": r[1], "vendor_url": r[2],
            "use_case": r[3], "category": r[4], "tags": tags,
            "next_review_date": r[5], "days_overdue": days_overdue,
            "created_at": r[6],
        })
    return result


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
        """SELECT v.id, v.name, v.vendor_url, v.use_case, v.category, v.next_review_date, v.created_at
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
            "use_case": r[3], "category": r[4], "tags": tags,
            "next_review_date": r[5], "created_at": r[6],
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
                "category": vendor["category"], "tags": vendor["tags"],
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
                "category": vendor["category"], "tags": vendor["tags"],
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
                  e.passed, e.failed, e.critical_fails, e.recommendations, e.answers, e.created_at
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
        "recommendations": json.loads(r[8]),
        "answers": json.loads(r[9]) if r[9] else {},
        "created_at": r[10],
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

    risk_counts = Counter(r[2] for r in latest)
    distribution = []
    for level in ["critical", "high", "medium", "low"]:
        cnt = risk_counts.get(level, 0)
        distribution.append({
            "level": level,
            "count": cnt,
            "pct": round(cnt / evaluated * 100, 1) if evaluated else 0,
        })

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

    critical_vendors = []
    for r in latest:
        if r[2] in ("critical", "high"):
            critical_vendors.append({
                "vendor_id": r[0], "vendor_name": r[4],
                "score": r[1], "risk_level": r[2],
                "top_fails": json.loads(r[3])[:3],
            })

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

    if len(scores) >= 2 and scores[0] < scores[1]:
        drop = scores[1] - scores[0]
        alerts.append({
            "type": "score_drop",
            "severity": "high" if drop >= 15 else "medium",
            "message": f"Score dropped by {drop} points (from {scores[1]} to {scores[0]})",
        })

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

    if len(scores) >= 3:
        declining = all(scores[i] <= scores[i+1] for i in range(len(scores)-1))
        if declining and scores[0] < scores[-1]:
            alerts.append({
                "type": "declining_trend",
                "severity": "medium",
                "message": f"Score has been declining over last {len(scores)} assessments ({scores[-1]} -> {scores[0]})",
            })

    if scores[0] < 50:
        alerts.append({
            "type": "below_threshold",
            "severity": "critical" if scores[0] < 30 else "high",
            "message": f"Current score ({scores[0]}) is below acceptable threshold (50)",
        })

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


# ── Contracts ────────────────────────────────────────────────────────────────

async def create_contract(db, vendor_id: int, data: dict) -> dict:
    if data.get("contract_type") and data["contract_type"] not in VALID_CONTRACT_TYPES:
        raise ValueError(f"Invalid contract_type. Valid: {', '.join(sorted(VALID_CONTRACT_TYPES))}")
    now = datetime.utcnow().isoformat()
    cur = await db.execute(
        """INSERT INTO vendor_contracts
           (vendor_id, contract_value, currency, renewal_date, auto_renew, contract_type, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (vendor_id, data["contract_value"], data.get("currency", "USD"),
         data["renewal_date"], int(data.get("auto_renew", False)),
         data.get("contract_type", "subscription"), data.get("notes"), now),
    )
    await db.commit()
    return await get_contract(db, cur.lastrowid)


async def get_contract(db, contract_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM vendor_contracts WHERE id=?", (contract_id,))
    r = await cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "vendor_id": r[1], "contract_value": r[2], "currency": r[3],
        "renewal_date": r[4], "auto_renew": bool(r[5]), "contract_type": r[6],
        "notes": r[7], "created_at": r[8],
    }


async def list_contracts(db, vendor_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM vendor_contracts WHERE vendor_id=? ORDER BY renewal_date ASC",
        (vendor_id,),
    )
    rows = await cur.fetchall()
    return [
        {"id": r[0], "vendor_id": r[1], "contract_value": r[2], "currency": r[3],
         "renewal_date": r[4], "auto_renew": bool(r[5]), "contract_type": r[6],
         "notes": r[7], "created_at": r[8]}
        for r in rows
    ]


async def update_contract(db, contract_id: int, updates: dict) -> dict | None:
    allowed = {"contract_value", "currency", "renewal_date", "auto_renew", "contract_type", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not fields:
        return await get_contract(db, contract_id)
    if "contract_type" in fields and fields["contract_type"] not in VALID_CONTRACT_TYPES:
        raise ValueError(f"Invalid contract_type. Valid: {', '.join(sorted(VALID_CONTRACT_TYPES))}")
    if "auto_renew" in fields:
        fields["auto_renew"] = int(fields["auto_renew"])
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [contract_id]
    cur = await db.execute(f"UPDATE vendor_contracts SET {set_clause} WHERE id=?", values)
    await db.commit()
    if cur.rowcount == 0:
        return None
    return await get_contract(db, contract_id)


async def delete_contract(db, contract_id: int) -> bool:
    cur = await db.execute("DELETE FROM vendor_contracts WHERE id=?", (contract_id,))
    await db.commit()
    return cur.rowcount > 0


async def get_expiring_contracts(db, within_days: int = 30) -> list[dict]:
    """Return contracts expiring within N days."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    deadline = (datetime.utcnow() + timedelta(days=within_days)).strftime("%Y-%m-%d")
    cur = await db.execute(
        """SELECT c.*, v.name as vendor_name
           FROM vendor_contracts c
           JOIN vendors v ON v.id = c.vendor_id
           WHERE c.renewal_date >= ? AND c.renewal_date <= ?
           ORDER BY c.renewal_date ASC""",
        (today, deadline),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        days_until = (datetime.strptime(r[4], "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
        result.append({
            "id": r[0], "vendor_id": r[1], "vendor_name": r[9],
            "contract_value": r[2], "currency": r[3],
            "renewal_date": r[4], "auto_renew": bool(r[5]),
            "contract_type": r[6], "notes": r[7],
            "days_until_renewal": days_until,
        })
    return result


# ── Category Stats ───────────────────────────────────────────────────────────

async def get_category_stats(db) -> list[dict]:
    """Per-category vendor count, average score, risk distribution."""
    cur = await db.execute(
        "SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as cnt FROM vendors GROUP BY cat ORDER BY cnt DESC"
    )
    categories = await cur.fetchall()
    result = []
    for cat_row in categories:
        cat = cat_row[0]
        count = cat_row[1]
        if cat == "uncategorized":
            score_cur = await db.execute(
                """SELECT e.total_score, e.risk_level FROM evaluations e
                   JOIN vendors v ON v.id = e.vendor_id
                   WHERE v.category IS NULL
                   AND e.id IN (SELECT MAX(id) FROM evaluations GROUP BY vendor_id)"""
            )
        else:
            score_cur = await db.execute(
                """SELECT e.total_score, e.risk_level FROM evaluations e
                   JOIN vendors v ON v.id = e.vendor_id
                   WHERE v.category = ?
                   AND e.id IN (SELECT MAX(id) FROM evaluations GROUP BY vendor_id)""",
                (cat,),
            )
        eval_rows = await score_cur.fetchall()
        scores = [r[0] for r in eval_rows]
        risk_dist = dict(Counter(r[1] for r in eval_rows))
        result.append({
            "category": cat,
            "vendor_count": count,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "risk_distribution": risk_dist,
        })
    return result


# ── v1.7.0: Vendor Dependencies ──────────────────────────────────────────────

async def _get_latest_eval(db, vendor_id: int) -> dict | None:
    cur = await db.execute(
        "SELECT total_score, risk_level FROM evaluations WHERE vendor_id=? ORDER BY id DESC LIMIT 1",
        (vendor_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    return {"score": r[0], "risk_level": r[1]}


async def add_dependency(db, vendor_id: int, depends_on_id: int, dependency_type: str, description: str | None) -> dict:
    if dependency_type not in VALID_DEPENDENCY_TYPES:
        raise ValueError(f"Invalid dependency_type. Valid: {', '.join(sorted(VALID_DEPENDENCY_TYPES))}")
    if vendor_id == depends_on_id:
        raise ValueError("A vendor cannot depend on itself")
    dep_vendor = await get_vendor(db, depends_on_id)
    if not dep_vendor:
        raise ValueError(f"Depends-on vendor {depends_on_id} not found")
    now = datetime.utcnow().isoformat()
    try:
        cur = await db.execute(
            """INSERT INTO vendor_dependencies (vendor_id, depends_on_id, dependency_type, description, created_at)
               VALUES (?,?,?,?,?)""",
            (vendor_id, depends_on_id, dependency_type, description, now),
        )
        await db.commit()
    except Exception:
        raise ValueError(f"Dependency already exists between vendor {vendor_id} and {depends_on_id}")
    return await get_dependency(db, cur.lastrowid)


async def get_dependency(db, dep_id: int) -> dict | None:
    cur = await db.execute(
        """SELECT d.id, d.vendor_id, d.depends_on_id, v.name, d.dependency_type,
                  d.description, d.created_at
           FROM vendor_dependencies d
           JOIN vendors v ON v.id = d.depends_on_id
           WHERE d.id = ?""",
        (dep_id,),
    )
    r = await cur.fetchone()
    if not r:
        return None
    eval_info = await _get_latest_eval(db, r[2])
    return {
        "id": r[0], "vendor_id": r[1], "depends_on_id": r[2],
        "depends_on_name": r[3], "dependency_type": r[4],
        "description": r[5],
        "depends_on_risk_level": eval_info["risk_level"] if eval_info else None,
        "depends_on_score": eval_info["score"] if eval_info else None,
        "created_at": r[6],
    }


async def list_dependencies(db, vendor_id: int) -> list[dict]:
    cur = await db.execute(
        """SELECT d.id, d.vendor_id, d.depends_on_id, v.name, d.dependency_type,
                  d.description, d.created_at
           FROM vendor_dependencies d
           JOIN vendors v ON v.id = d.depends_on_id
           WHERE d.vendor_id = ?
           ORDER BY d.dependency_type, v.name""",
        (vendor_id,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        eval_info = await _get_latest_eval(db, r[2])
        result.append({
            "id": r[0], "vendor_id": r[1], "depends_on_id": r[2],
            "depends_on_name": r[3], "dependency_type": r[4],
            "description": r[5],
            "depends_on_risk_level": eval_info["risk_level"] if eval_info else None,
            "depends_on_score": eval_info["score"] if eval_info else None,
            "created_at": r[6],
        })
    return result


async def remove_dependency(db, vendor_id: int, dep_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM vendor_dependencies WHERE id=? AND vendor_id=?", (dep_id, vendor_id)
    )
    await db.commit()
    return cur.rowcount > 0


async def get_dependency_tree(db, vendor_id: int, max_depth: int = 5) -> dict | None:
    vendor = await get_vendor(db, vendor_id)
    if not vendor:
        return None
    eval_info = await _get_latest_eval(db, vendor_id)

    async def _build_tree(vid: int, depth: int, visited: set) -> dict:
        v = await get_vendor(db, vid)
        ev = await _get_latest_eval(db, vid)
        node = {
            "vendor_id": vid,
            "vendor_name": v["name"] if v else "unknown",
            "risk_level": ev["risk_level"] if ev else None,
            "score": ev["score"] if ev else None,
            "dependencies": [],
        }
        if depth >= max_depth or vid in visited:
            return node
        visited.add(vid)
        deps = await list_dependencies(db, vid)
        for d in deps:
            child = await _build_tree(d["depends_on_id"], depth + 1, visited)
            child["dependency_type"] = d["dependency_type"]
            node["dependencies"].append(child)
        return node

    tree = await _build_tree(vendor_id, 0, set())

    # Collect chain info
    all_nodes = []
    critical_chain = []
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def _walk(node, depth=0):
        all_nodes.append(node)
        if node.get("risk_level") in ("critical", "high") and node["vendor_id"] != vendor_id:
            critical_chain.append({
                "vendor_id": node["vendor_id"],
                "vendor_name": node["vendor_name"],
                "risk_level": node["risk_level"],
                "score": node["score"],
                "dependency_type": node.get("dependency_type"),
            })
        for child in node.get("dependencies", []):
            _walk(child, depth + 1)

    _walk(tree)

    direct_deps = len(tree["dependencies"])
    risks = [n["risk_level"] for n in all_nodes if n["risk_level"]]
    highest = max(risks, key=lambda r: risk_order.get(r, 0)) if risks else None

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor["name"],
        "direct_dependencies": direct_deps,
        "total_chain_length": len(all_nodes) - 1,
        "highest_chain_risk": highest,
        "critical_chain_vendors": critical_chain,
        "tree": tree,
    }


# ── v1.7.0: Compliance Calendar & Matrix ─────────────────────────────────────

async def get_compliance_calendar(db, within_days: int = 90) -> dict:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    deadline = (datetime.utcnow() + timedelta(days=within_days)).strftime("%Y-%m-%d")

    cur = await db.execute(
        """SELECT c.vendor_id, v.name, c.framework, c.status, c.expires_at
           FROM vendor_compliance c
           JOIN vendors v ON v.id = c.vendor_id
           WHERE c.expires_at IS NOT NULL
           ORDER BY c.expires_at ASC"""
    )
    rows = await cur.fetchall()

    entries = []
    expired_count = 0
    expiring_soon_count = 0

    for r in rows:
        expires = r[4]
        days_until = (datetime.strptime(expires, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days

        if days_until < 0:
            urgency = "expired"
            expired_count += 1
        elif days_until <= 30:
            urgency = "critical"
            expiring_soon_count += 1
        elif days_until <= 60:
            urgency = "warning"
            expiring_soon_count += 1
        elif days_until <= within_days:
            urgency = "upcoming"
        else:
            continue

        entries.append({
            "vendor_id": r[0], "vendor_name": r[1],
            "framework": r[2], "status": r[3],
            "expires_at": expires, "days_until_expiry": days_until,
            "urgency": urgency,
        })

    return {
        "entries": entries,
        "total_expiring": len(entries),
        "expired_count": expired_count,
        "expiring_soon_count": expiring_soon_count,
    }


async def get_compliance_matrix(db) -> dict:
    vendors = await list_vendors(db)
    all_frameworks_set = set()
    matrix = []

    for v in vendors:
        compliance = await list_compliance(db, v["id"])
        fw_map = {}
        for c in compliance:
            fw_map[c["framework"]] = c["status"]
            all_frameworks_set.add(c["framework"])
        matrix.append({
            "vendor_id": v["id"],
            "vendor_name": v["name"],
            "frameworks": fw_map,
        })

    all_fw = sorted(all_frameworks_set)
    total_cells = len(vendors) * len(all_fw) if all_fw else 0
    covered = sum(len(m["frameworks"]) for m in matrix)
    coverage_pct = round(covered / total_cells * 100, 1) if total_cells else 0.0

    return {
        "vendors": matrix,
        "all_frameworks": all_fw,
        "total_vendors": len(vendors),
        "coverage_pct": coverage_pct,
    }


# ── v1.7.0: Assessment Diff ─────────────────────────────────────────────────

async def diff_evaluations(db, eval_a_id: int, eval_b_id: int) -> dict | None:
    a = await get_evaluation(db, eval_a_id)
    b = await get_evaluation(db, eval_b_id)
    if not a or not b:
        return None

    answers_a = a.get("answers", {})
    answers_b = b.get("answers", {})

    all_fields = sorted(set(list(answers_a.keys()) + list(answers_b.keys())))
    field_diffs = []
    for field in all_fields:
        val_a = str(answers_a.get(field, "N/A"))
        val_b = str(answers_b.get(field, "N/A"))
        field_diffs.append({
            "field": field,
            "eval_a": val_a,
            "eval_b": val_b,
            "changed": val_a != val_b,
        })

    crit_a = set(a["critical_fails"])
    crit_b = set(b["critical_fails"])
    rec_a = set(a["recommendations"])
    rec_b = set(b["recommendations"])

    return {
        "eval_a_id": eval_a_id,
        "eval_b_id": eval_b_id,
        "eval_a_vendor": a["vendor_name"],
        "eval_b_vendor": b["vendor_name"],
        "score_a": a["total_score"],
        "score_b": b["total_score"],
        "score_delta": b["total_score"] - a["total_score"],
        "risk_a": a["risk_level"],
        "risk_b": b["risk_level"],
        "risk_changed": a["risk_level"] != b["risk_level"],
        "fields": field_diffs,
        "new_critical_fails": sorted(crit_b - crit_a),
        "resolved_critical_fails": sorted(crit_a - crit_b),
        "new_recommendations": sorted(rec_b - rec_a),
        "resolved_recommendations": sorted(rec_a - rec_b),
    }


# ── v1.8.0: Vendor Contacts ─────────────────────────────────────────────────

async def create_contact(db, vendor_id: int, data: dict) -> dict:
    now = datetime.utcnow().isoformat()
    is_primary = int(data.get("is_primary", False))
    if is_primary:
        await db.execute(
            "UPDATE vendor_contacts SET is_primary = 0 WHERE vendor_id = ?",
            (vendor_id,),
        )
    cur = await db.execute(
        """INSERT INTO vendor_contacts (vendor_id, name, email, role, phone, is_primary, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (vendor_id, data["name"], data.get("email"), data.get("role"),
         data.get("phone"), is_primary, now),
    )
    await db.commit()
    return _contact_row(await _fetch_contact(db, cur.lastrowid))


async def _fetch_contact(db, contact_id: int):
    cur = await db.execute("SELECT * FROM vendor_contacts WHERE id=?", (contact_id,))
    return await cur.fetchone()


def _contact_row(r) -> dict:
    if not r:
        return {}
    return {
        "id": r[0], "vendor_id": r[1], "name": r[2], "email": r[3],
        "role": r[4], "phone": r[5], "is_primary": bool(r[6]), "created_at": r[7],
    }


async def list_contacts(db, vendor_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM vendor_contacts WHERE vendor_id=? ORDER BY is_primary DESC, name ASC",
        (vendor_id,),
    )
    rows = await cur.fetchall()
    return [_contact_row(r) for r in rows]


async def update_contact(db, contact_id: int, updates: dict) -> dict | None:
    allowed = {"name", "email", "role", "phone", "is_primary"}
    fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not fields:
        r = await _fetch_contact(db, contact_id)
        return _contact_row(r) if r else None

    if fields.get("is_primary"):
        r = await _fetch_contact(db, contact_id)
        if r:
            await db.execute(
                "UPDATE vendor_contacts SET is_primary = 0 WHERE vendor_id = ?",
                (r[1],),
            )
        fields["is_primary"] = int(fields["is_primary"])
    elif "is_primary" in fields:
        fields["is_primary"] = int(fields["is_primary"])

    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [contact_id]
    cur = await db.execute(f"UPDATE vendor_contacts SET {set_clause} WHERE id=?", values)
    await db.commit()
    if cur.rowcount == 0:
        return None
    r = await _fetch_contact(db, contact_id)
    return _contact_row(r)


async def delete_contact(db, contact_id: int) -> bool:
    cur = await db.execute("DELETE FROM vendor_contacts WHERE id=?", (contact_id,))
    await db.commit()
    return cur.rowcount > 0


# ── v1.8.0: Bulk Assessment ──────────────────────────────────────────────────

async def bulk_assess(db, items: list[dict]) -> dict:
    results = []
    skipped = 0
    for item in items:
        vendor = await get_vendor(db, item["vendor_id"])
        if not vendor:
            skipped += 1
            continue
        assessment = await assess_vendor(db, item["vendor_id"], item["answers"])
        results.append({
            "vendor_id": item["vendor_id"],
            "vendor_name": assessment["vendor_name"],
            "total_score": assessment["total_score"],
            "risk_level": assessment["risk_level"],
            "critical_fails": assessment["critical_fails"],
        })

    scores = [r["total_score"] for r in results]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    risk_dist = dict(Counter(r["risk_level"] for r in results))

    return {
        "assessed": len(results),
        "skipped": skipped,
        "results": results,
        "avg_score": avg_score,
        "risk_distribution": risk_dist,
    }


# ── v1.8.0: Portfolio CSV Export ─────────────────────────────────────────────

async def export_portfolio_csv(db) -> str:
    import csv, io
    vendors = await list_vendors(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "vendor_id", "name", "category", "tags", "vendor_url", "use_case",
        "next_review_date", "latest_score", "risk_level",
        "compliance_frameworks", "compliance_statuses",
        "total_contract_value", "contract_currencies",
        "contacts_count", "primary_contact_name", "primary_contact_email",
    ])

    for v in vendors:
        # Latest evaluation
        eval_info = await _get_latest_eval(db, v["id"])
        score = eval_info["score"] if eval_info else ""
        risk = eval_info["risk_level"] if eval_info else ""

        # Compliance
        compliance = await list_compliance(db, v["id"])
        fw_list = "|".join(c["framework"] for c in compliance)
        status_list = "|".join(f"{c['framework']}:{c['status']}" for c in compliance)

        # Contracts
        contracts = await list_contracts(db, v["id"])
        total_value = sum(c["contract_value"] for c in contracts)
        currencies = "|".join(sorted(set(c["currency"] for c in contracts))) if contracts else ""

        # Contacts
        contacts = await list_contacts(db, v["id"])
        primary = next((c for c in contacts if c["is_primary"]), contacts[0] if contacts else None)
        primary_name = primary["name"] if primary else ""
        primary_email = primary["email"] if primary else ""

        writer.writerow([
            v["id"], v["name"], v.get("category", ""), "|".join(v.get("tags", [])),
            v.get("vendor_url", ""), v.get("use_case", ""),
            v.get("next_review_date", ""), score, risk,
            fw_list, status_list,
            total_value if contracts else "", currencies,
            len(contacts), primary_name, primary_email,
        ])
    return buf.getvalue()
