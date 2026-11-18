from app.report import report

def collisions(rows):
    """同一复本同一期被不同装订号 claim 时，列出双侧（及多侧）证据。

    同装订号的重复记录不算冲突；不同复本各自独立，也不算冲突。
    证据保留 record_id、binding 与原始行号，供实物核验定位。
    """
    claims = {}
    for r in rows:
        if r["status"] != "held":
            continue
        for issue in r["issues"]:
            key = (r["journal_key"], r["year"], issue, r["copy"])
            claims.setdefault(key, []).append(r)
    conflicts = []
    for (issn, year, issue, copy), owners in claims.items():
        bindings = {o["binding"] for o in owners}
        if len(bindings) <= 1:
            continue
        owners_sorted = sorted(owners, key=lambda o: (str(o.get("line", 0)), o["record_id"]))
        conflicts.append({
            "reason": "BINDING_CONFLICT",
            "issn": issn,
            "title": owners[0].get("canonical", ""),
            "year": year,
            "copy": copy,
            "issue": issue,
            "left": owners_sorted[0]["record_id"],
            "right": owners_sorted[-1]["record_id"],
            "bindings": sorted(bindings),
            "claimants": [
                {"record_id": o["record_id"], "binding": o["binding"], "line": o.get("line", 0)}
                for o in owners_sorted
            ],
        })
    conflicts.sort(key=lambda c: (c["issn"], c["year"], c["copy"], int(c["issue"])))
    return conflicts

def apply(ctx):
    conflict = collisions(ctx["expanded"])
    ctx["binding_conflicts"] = conflict
    out = [dict(r, physical_books=1, covered_issues=len(r["issues"]))
           for r in ctx["expanded"] if r["status"] == "held"]
    ctx["held"] = out
    return report(out, 合刊=sum(len(r["issues"]) > 1 for r in out), 装订冲突=len(conflict))
