from app.report import report

CONFIRMED_MISSING = "确缺"
PENDING_VERIFY = "待查"
SUSPENDED = "停刊"
HELD = "在馆"

REASON_LABELS = {
    "CONFIRMED_MISSING": "无在馆覆盖且未停刊，可开补录单",
    "BINDING_CONFLICT": "同一复本期次被多个装订号覆盖，待实物核验",
    "SUSPENDED": "明确停刊，不补录",
    "VERIFY_HELD": "实物核验在馆，不补录",
    "VERIFY_MISSING": "实物核验确缺，可开补录单",
    "IDENTITY_CONFLICT": "刊名身份冲突，阻断复核",
}

def item_key(issn, year, copy, issue):
    return "|".join([issn, str(year), str(copy or ""), str(issue)])

def _verdict_index(verifications):
    return {v["item_key"]: v for v in (verifications or [])}

def build_review(gaps, verifications=None, identity_conflicts=None):
    """构造补录复核逐项清单：每项带状态与原因，页面可直接解释为何待查/可开单。"""
    verdicts = _verdict_index(verifications)
    identity_set = set(identity_conflicts or [])
    items = []
    unresolved = False
    for g in gaps:
        base = {"issn": g["issn"], "title": g["title"], "year": g["year"]}
        for p in g.get("pending", []):
            key = item_key(g["issn"], g["year"], p["copy"], p["issue"])
            verdict = verdicts.get(key)
            if verdict is None:
                unresolved = True
                status, reason = PENDING_VERIFY, "BINDING_CONFLICT"
            elif verdict["conclusion"] == "held":
                status, reason = HELD, "VERIFY_HELD"
            else:
                status, reason = CONFIRMED_MISSING, "VERIFY_MISSING"
            items.append({
                **base, "copy": p["copy"], "issue": p["issue"], "item_key": key,
                "status": status, "reason": reason, "reason_label": REASON_LABELS[reason],
                "orderable": status == CONFIRMED_MISSING,
                "evidence": {"claimants": p.get("claimants", []), "verification": verdict},
            })
        for issue in g.get("missing", []):
            key = item_key(g["issn"], g["year"], "", issue)
            verdict = verdicts.get(key)
            if verdict is not None and verdict["conclusion"] == "held":
                status, reason = HELD, "VERIFY_HELD"
            else:
                status, reason = CONFIRMED_MISSING, "VERIFY_MISSING" if verdict else "CONFIRMED_MISSING"
            items.append({
                **base, "copy": "", "issue": issue, "item_key": key,
                "status": status, "reason": reason, "reason_label": REASON_LABELS[reason],
                "orderable": status == CONFIRMED_MISSING,
                "evidence": {"verification": verdict},
            })
        for issue in g.get("suspended", []):
            items.append({
                **base, "copy": "", "issue": issue,
                "item_key": item_key(g["issn"], g["year"], "", issue),
                "status": SUSPENDED, "reason": "SUSPENDED",
                "reason_label": REASON_LABELS["SUSPENDED"], "orderable": False, "evidence": {},
            })
    blocked = unresolved or bool(identity_set)
    for it in items:
        if it["issn"] in identity_set:
            it["identity_conflict"] = True
    return items, blocked

def request_list(gaps, verifications=None, identity_conflicts=None):
    items, _ = build_review(gaps, verifications, identity_conflicts)
    return items

def apply(ctx):
    items, blocked = build_review(ctx["gaps"], ctx.get("verifications"),
                                  ctx.get("identity_conflicts"))
    ctx["final"] = items
    ctx["blocked"] = blocked
    return report(
        items,
        补录任务=len(items),
        可开单=sum(1 for i in items if i["orderable"]),
        待查=sum(1 for i in items if i["status"] == PENDING_VERIFY),
        冲突=len(ctx.get("binding_conflicts", [])) + len(ctx.get("identity_conflicts", [])),
    )
