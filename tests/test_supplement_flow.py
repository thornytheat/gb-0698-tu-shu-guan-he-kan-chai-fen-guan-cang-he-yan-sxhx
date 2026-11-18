import pytest
from pathlib import Path
from app.pipeline import run
from app import store
from app.errors import BusinessError
from app.exporter import evidence_csv

DISPUTE = (Path(__file__).parent.parent / "sample_data" / "binding-dispute.csv").read_text(encoding="utf-8")

@pytest.fixture
def batch():
    # 每个用例独立数据库：核验会推进 revision 并写入结论，避免用例间相互污染
    store.connect().close()
    db_path = store.DATA_DIR / "runs.sqlite"
    db_path.unlink(missing_ok=True)
    return store.save(DISPUTE, run(DISPUTE))

def _pending_key(view):
    return next(i["item_key"] for i in view["items"] if i["status"] == "待查")

def test_pending_blocks_review_pass(batch):
    with pytest.raises(BusinessError, match="待查"):
        store.review(batch["id"], batch["revision"], "通过")

def test_opposite_verifications_do_not_mix(batch):
    view = store.review_view(batch["id"])
    key = _pending_key(view)
    rev = view["revision"]
    # 甲先提交 missing，成功并推进版本
    store.submit_verification(batch["id"], rev, key, "missing", "甲")
    # 乙持旧版本同时提交相反结论 held → 409，补录单不会混用两份结论
    with pytest.raises(BusinessError) as caught:
        store.submit_verification(batch["id"], rev, key, "held", "乙")
    assert caught.value.status == 409 and caught.value.code == "STALE"
    view = store.review_view(batch["id"])
    kept = next(v for v in view["verifications"] if v["item_key"] == key)
    assert kept["conclusion"] == "missing" and kept["reviewer"] == "甲"

def test_verification_resolves_blocking_and_pass(batch):
    view = store.review_view(batch["id"])
    key = _pending_key(view)
    updated = store.submit_verification(batch["id"], view["revision"], key, "missing", "甲")
    assert store.review_view(batch["id"])["blocked"] is False
    out = store.review(batch["id"], updated["revision"], "通过")
    assert out["decision"] == "通过"

def test_verification_held_removes_item_from_order(batch):
    view = store.review_view(batch["id"])
    key = _pending_key(view)
    store.submit_verification(batch["id"], view["revision"], key, "held", "乙")
    view = store.review_view(batch["id"])
    item = next(i for i in view["items"] if i["item_key"] == key)
    assert item["status"] == "在馆" and item["orderable"] is False

def test_order_idempotent_on_retry(batch):
    first = store.create_order(batch["id"])
    second = store.create_order(batch["id"])
    assert first["order_no"] == second["order_no"]
    assert first["idempotent"] is False and second["idempotent"] is True
    assert [ln["issue"] for ln in first["lines"]] == [ln["issue"] for ln in second["lines"]]

def test_order_appends_resolved_item_with_stable_line_numbers(batch):
    # 挂起期查清后追加到同一张单：原行号不动，重试仍不重复开单
    first = store.create_order(batch["id"])
    view = store.review_view(batch["id"])
    key = next(i["item_key"] for i in view["items"] if i["status"] == "待查")
    store.submit_verification(batch["id"], view["revision"], key, "missing", "甲")
    second = store.create_order(batch["id"])
    assert second["order_no"] == first["order_no"] and second["idempotent"] is True
    assert [ln["issue"] for ln in second["lines"]] == ["11", "2"]
    # 再次重试内容与行号完全一致
    third = store.create_order(batch["id"])
    assert [(ln["line_no"], ln["item_key"]) for ln in third["lines"]] == \
           [(ln["line_no"], ln["item_key"]) for ln in second["lines"]]

def test_order_while_pending_excludes_disputed(batch):
    # 月底补录单按时发：待查期挂起，确缺期照常放行，馆员不会被未查清的装订冲突白跑
    order = store.create_order(batch["id"])
    issues = {ln["issue"] for ln in order["lines"]}
    assert issues == {"11"}
    assert order["excluded_pending"] == [next(
        i["item_key"] for i in store.review_view(batch["id"])["items"] if i["status"] == "待查")]
    # 复核归档仍被待查阻断
    with pytest.raises(BusinessError, match="待查"):
        store.review(batch["id"], batch["revision"], "通过")

def test_order_contains_only_orderable(batch):
    view = store.review_view(batch["id"])
    key = _pending_key(view)
    store.submit_verification(batch["id"], view["revision"], key, "held", "乙")
    order = store.create_order(batch["id"])
    # 第2期实物在馆 → 不在单内；停刊第12期不在单内；仅确缺期次开单
    issues = {ln["issue"] for ln in order["lines"]}
    assert "2" not in issues and "12" not in issues and "11" in issues
    assert all(ln["reason_label"] for ln in order["lines"])

def test_unknown_item_rejected(batch):
    with pytest.raises(BusinessError) as caught:
        store.submit_verification(batch["id"], batch["revision"], "nope", "held", "甲")
    assert caught.value.status == 404

def test_bad_conclusion_rejected(batch):
    view = store.review_view(batch["id"])
    with pytest.raises(BusinessError, match="结论"):
        store.submit_verification(batch["id"], view["revision"], _pending_key(view), "maybe", "甲")

def test_review_view_explains_every_item(batch):
    view = store.review_view(batch["id"])
    assert view["blocked"] is True
    for item in view["items"]:
        assert item["reason"] and item["reason_label"] and "item_key" in item

def test_evidence_csv_contains_verification_and_order(batch):
    view = store.review_view(batch["id"])
    key = _pending_key(view)
    store.submit_verification(batch["id"], view["revision"], key, "missing", "甲")
    store.create_order(batch["id"])
    text = evidence_csv(store.get(batch["id"]))
    assert "verification" in text and "supplement_order" in text and batch["digest"] in text

def test_identity_conflict_blocks_archival_not_order():
    from app.pipeline import run as run_pipeline
    text = ("record_id,title,issn,year,volume,issue,copy,binding,status,note\n"
            "X1,甲刊,4000-0001,2026,001,1,01,X1,held,\n"
            "X2,乙刊,4000-0001,2026,001,3,01,X2,held,\n")
    b = store.save(text, run_pipeline(text))
    assert store.review_view(b["id"])["blocked"] is True
    with pytest.raises(BusinessError, match="阻断"):
        store.review(b["id"], b["revision"], "通过")
    order = store.create_order(b["id"])
    assert "2" in {ln["issue"] for ln in order["lines"]}

def test_no_orderable_rejected():
    from app.pipeline import run as run_pipeline
    text = "record_id,title,issn,year,volume,issue,copy,binding,status,note\n" \
           "C1,刊,3000-0001,2026,001,1-12,01,C1,held,齐\n"
    b = store.save(text, run_pipeline(text))
    with pytest.raises(BusinessError, match="可开单"):
        store.create_order(b["id"])
