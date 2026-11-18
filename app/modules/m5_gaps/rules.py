from app.report import report

def missing(covered, suspended, expected=12):
    """确缺：1..N 中既无在馆覆盖、也未明确停刊的期次。"""
    return sorted(set(map(str, range(1, expected + 1))) - set(covered) - set(suspended), key=int)

def disputed_keys(conflicts):
    """装订冲突覆盖到的 (issn, year, copy, issue) —— 这些期次身份不明，只能待查，不能直接判缺。"""
    return {(c["issn"], c["year"], c["copy"], c["issue"]): c for c in conflicts}

def apply(ctx):
    groups = {}
    for r in ctx["expanded"]:
        groups.setdefault((r["journal_key"], r["year"], r["canonical"]), []).append(r)
    disputes = disputed_keys(ctx.get("binding_conflicts", []))
    out = []
    for (issn, year, title), rows in groups.items():
        covered = {i for r in rows if r["status"] == "held" for i in r["issues"]}
        suspended = {i for r in rows if r["status"] == "suspended" for i in r["issues"]}
        pending = []
        for (c_issn, c_year, copy, issue), conflict in disputes.items():
            if c_issn == issn and c_year == year:
                pending.append({
                    "copy": copy,
                    "issue": issue,
                    "status": "待查",
                    "reason": "BINDING_CONFLICT",
                    "reason_label": "装订冲突待实物核验",
                    "claimants": conflict["claimants"],
                })
        pending.sort(key=lambda p: (p["copy"], int(p["issue"])))
        # 待查按 (复本, 期) 定位；确缺集合在刊/年维度计算，凡有任一复本待查的期即不判确缺
        pending_issues = {p["issue"] for p in pending}
        absent = [i for i in missing(covered, suspended) if i not in pending_issues]
        out.append({
            "issn": issn,
            "title": title,
            "year": year,
            "missing": absent,
            "pending": pending,
            "covered": sorted(covered, key=int),
            "suspended": sorted(suspended, key=int),
            "status": "GAP" if absent or pending else "COMPLETE",
        })
    ctx["gaps"] = out
    return report(out, 缺期=sum(len(r["missing"]) for r in out),
                  待查=sum(len(r["pending"]) for r in out), 年度=len(out))
