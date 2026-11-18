# TRAP-23
from app.modules.m5_gaps.rules import *
from app.errors import BusinessError
import pytest
from pathlib import Path

DISPUTE = (Path(__file__).parent.parent / "sample_data" / "binding-dispute.csv").read_text(encoding="utf-8")

def _run(text):
    from app.pipeline import run
    return run(text)

def test_gap_suspended():
    assert missing(["1", "2"], ["3"], 4) == ["4"]

def test_gap_supplement():
    assert missing(["S1"], [], 2) == ["1", "2"]

def test_gap_complete():
    assert missing(["1", "2"], [], 2) == []

def test_gap_empty():
    assert missing([], [], 2) == ["1", "2"]

def test_gap_sample(result):
    assert len(result["gaps"]) == 4

def test_gap_expected(result):
    assert any(r["status"] == "GAP" for r in result["gaps"])

def test_gap_no_suspended(result):
    assert all("12" not in r["missing"] for r in result["gaps"] if "12" in r["suspended"])

def test_dispute_split_pending_and_confirmed():
    r = _run(DISPUTE)
    g = r["gaps"][0]
    # 第2期冲突 → 待查；第11期无覆盖 → 确缺；待查不得混进确缺集合
    assert [p["issue"] for p in g["pending"]] == ["2"]
    assert "2" not in g["missing"]
    assert "11" in g["missing"]
    assert g["pending"][0]["reason"] == "BINDING_CONFLICT"
    assert {c["binding"] for c in g["pending"][0]["claimants"]} == {"DB01", "DB02"}

def test_disputed_keys_helper():
    conflicts = [{"issn": "i", "year": "2026", "copy": "01", "issue": "2",
                  "claimants": []}]
    keys = disputed_keys(conflicts)
    assert ("i", "2026", "01", "2") in keys

def test_multi_copy_dispute_isolated_per_copy():
    # 复本01在第2期装订冲突（待查）；复本02同刊同年，缺期定位互不串号
    rows = [
        {"journal_key": "i", "canonical": "刊", "year": "2026", "status": "held",
         "issues": ["1", "2"], "copy": "01", "binding": "B1", "record_id": "a", "line": 2},
        {"journal_key": "i", "canonical": "刊", "year": "2026", "status": "held",
         "issues": ["2"], "copy": "01", "binding": "B2", "record_id": "b", "line": 3},
        {"journal_key": "i", "canonical": "刊", "year": "2026", "status": "held",
         "issues": ["1"], "copy": "02", "binding": "C1", "record_id": "c", "line": 4},
    ]
    from app.modules.m4_combined.rules import collisions
    ctx = {"expanded": rows, "binding_conflicts": collisions(rows)}
    apply(ctx)
    g = ctx["gaps"][0]
    assert [p["copy"] for p in g["pending"]] == ["01"]
    assert g["pending"][0]["issue"] == "2"
    assert "2" not in g["missing"]
