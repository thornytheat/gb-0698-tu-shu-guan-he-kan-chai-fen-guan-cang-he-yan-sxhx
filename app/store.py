import sqlite3, json, hashlib
from datetime import datetime, timezone
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "runs.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '待复核', created TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS verifications (run_id TEXT NOT NULL, item_key TEXT NOT NULL, conclusion TEXT NOT NULL, reviewer TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(run_id,item_key))")
    db.execute("CREATE TABLE IF NOT EXISTS supplement_orders (run_id TEXT PRIMARY KEY, order_no TEXT NOT NULL, created TEXT NOT NULL, lines TEXT NOT NULL)")
    return db

def save(text, result):
    digest = hashlib.sha256((RULE_VERSION + "\n" + text).encode()).hexdigest()
    ident = digest[:16]
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,digest,result,created) VALUES(?,?,?,?)",
                   (ident, digest, json.dumps(dict(result, rule_version=RULE_VERSION), ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat()))
    return get(ident)

def get(ident):
    with connect() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise BusinessError("NOT_FOUND", "批次不存在", 404)
    item = dict(row)
    item["result"] = json.loads(item["result"])
    item["rule_version"] = item["result"].get("rule_version", "2026.11.18.1")
    return item

def history():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,revision,decision,created FROM runs ORDER BY created DESC LIMIT 40")]

def review(ident, revision, decision):
    if not isinstance(decision, str) or decision not in {"通过", "退回"}:
        raise BusinessError("DECISION", "复核决定无效")
    current = get(ident)
    if decision == "通过" and effective_blocked(ident):
        raise BusinessError("BLOCKED", "存在待查冲突或身份阻断项，请先按实物结论处理", 409)
    with connect() as db:
        changed = db.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",
                             (decision, ident, revision)).rowcount
        if not changed:
            raise BusinessError("STALE", "版本已更新，请刷新", 409)
    return get(ident)

# ---------------------------------------------------------------- verifications

def list_verifications(ident):
    get(ident)
    with connect() as db:
        rows = db.execute("SELECT item_key,conclusion,reviewer,created FROM verifications WHERE run_id=? ORDER BY created",
                          (ident,)).fetchall()
    return [dict(r) for r in rows]

def _valid_item_keys(result):
    keys = set()
    for g in result.get("gaps", []):
        for p in g.get("pending", []):
            keys.add("|".join([g["issn"], g["year"], p["copy"], p["issue"]]))
        for issue in g.get("missing", []):
            keys.add("|".join([g["issn"], g["year"], "", issue]))
    return keys

def submit_verification(ident, revision, item_key, conclusion, reviewer):
    if type(revision) is not int:
        raise BusinessError("REVISION", "版本须为整数")
    if not isinstance(item_key, str) or not item_key:
        raise BusinessError("REVIEW", "核验项编号须为文本")
    if conclusion not in {"held", "missing"}:
        raise BusinessError("CONCLUSION", "核验结论须为 held 或 missing")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise BusinessError("REVIEWER", "核验人须为文本")
    current = get(ident)
    if item_key not in _valid_item_keys(current["result"]):
        raise BusinessError("ITEM_NOT_FOUND", "核验项不属于该批次或缺期/冲突范围", 404)
    ts = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        # 乐观锁：以 runs.revision 为版本，两人同时提交相反结论时后者 409，结论不混用
        changed = db.execute("UPDATE runs SET revision=revision+1 WHERE id=? AND revision=?",
                             (ident, revision)).rowcount
        if not changed:
            raise BusinessError("STALE", "版本已更新，存在并发核验，请刷新后以最新结论为准", 409)
        db.execute("INSERT INTO verifications(run_id,item_key,conclusion,reviewer,created) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(run_id,item_key) DO UPDATE SET conclusion=excluded.conclusion,reviewer=excluded.reviewer,created=excluded.created",
                   (ident, item_key, conclusion, reviewer.strip(), ts))
    return get(ident)

# ----------------------------------------------------------- supplement orders

def _review_items(ident):
    from app.modules.m7_supplement.rules import build_review
    item = get(ident)
    items, blocked = build_review(item["result"].get("gaps", []), list_verifications(ident),
                                  item["result"].get("identity_conflicts", []))
    return item, items, blocked

def effective_blocked(ident):
    _, _, blocked = _review_items(ident)
    return blocked

def review_view(ident):
    item, items, blocked = _review_items(ident)
    order = get_order(ident)
    return {
        "id": ident,
        "revision": item["revision"],
        "decision": item["decision"],
        "blocked": blocked,
        "items": items,
        "verifications": list_verifications(ident),
        "order": order,
    }

def get_order(ident):
    get(ident)
    with connect() as db:
        row = db.execute("SELECT order_no,created,lines FROM supplement_orders WHERE run_id=?", (ident,)).fetchone()
    if row is None:
        return None
    return {"order_no": row["order_no"], "created": row["created"], "lines": json.loads(row["lines"])}

def create_order(ident):
    """生成补录单：只放行确缺（可开单）期次，待查/停刊/在馆项不入单。

    重试不重复开单：同一批次只有一张补录单，重复请求复用同一单号；
    挂起期次查清后再次调用，新可开单项追加到原单，已分配行号保持不变。
    """
    item, items, blocked = _review_items(ident)
    orderable = [i for i in items if i["orderable"]]
    if not orderable:
        raise BusinessError("NO_ORDERABLE", "没有可开单的确缺期次，待查期次请先按实物结论处理")
    ts = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        existing = db.execute("SELECT order_no,lines FROM supplement_orders WHERE run_id=?",
                              (ident,)).fetchone()
        if existing is not None:
            order_no = existing["order_no"]
            old_lines = json.loads(existing["lines"])
            numbering = {ln["item_key"]: ln["line_no"] for ln in old_lines}
            next_no = (max(numbering.values()) if numbering else 0) + 1
        else:
            order_no, numbering, next_no = "BL" + ident[:10], {}, 1
        lines = []
        for i in orderable:
            if i["item_key"] not in numbering:
                numbering[i["item_key"]] = next_no
                next_no += 1
            lines.append({
                "line_no": numbering[i["item_key"]], "item_key": i["item_key"],
                "issn": i["issn"], "title": i["title"], "year": i["year"],
                "copy": i["copy"], "issue": i["issue"], "reason": i["reason"],
                "reason_label": i["reason_label"],
            })
        lines.sort(key=lambda ln: ln["line_no"])
        db.execute("INSERT INTO supplement_orders(run_id,order_no,created,lines) VALUES(?,?,?,?) "
                   "ON CONFLICT(run_id) DO UPDATE SET lines=excluded.lines",
                   (ident, order_no, ts, json.dumps(lines, ensure_ascii=False)))
    return {"order_no": order_no, "created": ts, "lines": lines,
            "idempotent": existing is not None,
            "excluded_pending": [i["item_key"] for i in items if i["status"] == "待查"]}
