from app.modules.m7_supplement.rules import *
from app.errors import BusinessError
import pytest
from pathlib import Path

DISPUTE = (Path(__file__).parent.parent / "sample_data" / "binding-dispute.csv").read_text(encoding="utf-8")

def _run(text):
    from app.pipeline import run
    return run(text)

def test_supplement_plan():
    items = request_list([{"issn": "i", "title": "a", "year": "2026",
                           "missing": ["2", "3"], "pending": [], "suspended": []}])
    assert [i["issue"] for i in items] == ["2", "3"]
    assert all(i["status"] == "确缺" and i["orderable"] for i in items)

def test_supplement_empty():
    assert request_list([]) == []

def test_supplement_covered():
    items = request_list([{"issn": "i", "title": "a", "year": "2026",
                           "missing": [], "pending": [], "suspended": []}])
    assert items == []

def test_supplement_sample(result):
    assert len(result["final"]) > 0

def test_supplement_clear(result):
    assert result["blocked"] is False

def test_supplement_unique(result):
    keys = {(r["issn"], r["year"], r["copy"], r["issue"]) for r in result["final"]}
    assert len(keys) == len(result["final"])

def test_supplement_status(result):
    # 无冲突批次：缺期直接判确缺，停刊期单列且不可开单
    assert all(r["status"] in {"确缺", "停刊"} for r in result["final"])
    assert all(r["orderable"] == (r["status"] == "确缺") for r in result["final"])

def test_dispute_pending_vs_confirmed():
    r = _run(DISPUTE)
    by_issue = {i["issue"]: i for i in r["final"]}
    # 第2期装订冲突 → 待查、不可开单、带双侧证据
    p = by_issue["2"]
    assert p["status"] == "待查" and p["reason"] == "BINDING_CONFLICT"
    assert p["orderable"] is False
    assert {c["binding"] for c in p["evidence"]["claimants"]} == {"DB01", "DB02"}
    # 第11期无人覆盖且未停刊 → 确缺、可开单
    m = by_issue["11"]
    assert m["status"] == "确缺" and m["reason"] == "CONFIRMED_MISSING" and m["orderable"] is True
    # 第12期停刊 → 不补录
    assert by_issue["12"]["status"] == "停刊" and by_issue["12"]["orderable"] is False
    # 待查未核验前整批阻断
    assert r["blocked"] is True

def test_dispute_resolved_missing_then_orderable():
    r = _run(DISPUTE)
    pending = next(i for i in r["final"] if i["status"] == "待查")
    items, blocked = build_review(r["gaps"], [
        {"item_key": pending["item_key"], "conclusion": "missing", "reviewer": "甲"}],
        r["identity_conflicts"])
    verdict = next(i for i in items if i["item_key"] == pending["item_key"])
    assert verdict["status"] == "确缺" and verdict["reason"] == "VERIFY_MISSING" and verdict["orderable"]
    assert blocked is False

def test_dispute_resolved_held_not_orderable():
    r = _run(DISPUTE)
    pending = next(i for i in r["final"] if i["status"] == "待查")
    items, blocked = build_review(r["gaps"], [
        {"item_key": pending["item_key"], "conclusion": "held", "reviewer": "乙"}],
        r["identity_conflicts"])
    verdict = next(i for i in items if i["item_key"] == pending["item_key"])
    assert verdict["status"] == "在馆" and verdict["orderable"] is False
    assert blocked is False

def test_every_item_has_reason(result):
    # 补录复核页面要能查到每项为何待查或可开单
    assert all(i.get("reason") and i.get("reason_label") for i in result["final"])
