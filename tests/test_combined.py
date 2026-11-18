# TRAP-14
from app.modules.m4_combined.rules import *
from app.errors import BusinessError
import pytest

def test_combined_sample(result):
    assert len(result["held"]) == 40

def test_combined_physical(result):
    assert any(r["physical_books"] == 1 and r["covered_issues"] == 2 for r in result["held"])

def test_combined_no_conflicts(result):
    assert result["binding_conflicts"] == []

def test_combined_duplicate():
    r = {"journal_key": "i", "year": "2026", "issues": ["1"], "copy": "01",
         "binding": "a", "record_id": "1", "status": "held", "line": 2}
    c = collisions([r, dict(r, binding="b", record_id="2", line=3)])[0]
    assert c["reason"] == "BINDING_CONFLICT"
    # 双侧证据都要列出，馆员据此定位实物，不静默采信任一侧
    assert [x["record_id"] for x in c["claimants"]] == ["1", "2"]
    assert c["bindings"] == ["a", "b"]
    assert c["left"] == "1" and c["right"] == "2"

def test_combined_overlapping_ranges():
    # 同一复本两条装订记录分别覆盖 1-2 与 2-3：只在重叠的第2期冲突
    a = {"journal_key": "i", "year": "2026", "issues": ["1", "2"], "copy": "01",
         "binding": "B1", "record_id": "1", "status": "held", "line": 2, "canonical": "刊"}
    b = {"journal_key": "i", "year": "2026", "issues": ["2", "3"], "copy": "01",
         "binding": "B2", "record_id": "2", "status": "held", "line": 3, "canonical": "刊"}
    c = collisions([a, b])
    assert len(c) == 1 and c[0]["issue"] == "2"
    assert {x["binding"] for x in c[0]["claimants"]} == {"B1", "B2"}

def test_combined_copies():
    r = {"journal_key": "i", "year": "2026", "issues": ["1"], "copy": "01",
         "binding": "a", "record_id": "1", "status": "held"}
    assert collisions([r, dict(r, copy="02", binding="b")]) == []

def test_combined_missing():
    assert collisions([]) == []

def test_combined_same_bind():
    r = {"journal_key": "i", "year": "2026", "issues": ["1"], "copy": "01",
         "binding": "a", "record_id": "1", "status": "held"}
    assert collisions([r, r]) == []
