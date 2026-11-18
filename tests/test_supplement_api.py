from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import store
from app.pipeline import run

client = TestClient(app, raise_server_exceptions=False)
DISPUTE = (Path(__file__).parent.parent / "sample_data" / "binding-dispute.csv").read_text(encoding="utf-8")

import pytest

@pytest.fixture(autouse=True)
def reset_store():
    (store.DATA_DIR / "runs.sqlite").unlink(missing_ok=True)
    yield

def _batch():
    return store.save(DISPUTE, run(DISPUTE))

def test_supplement_view_endpoint():
    b = _batch()
    r = client.get(f"/api/supplement/{b['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert any(i["status"] == "待查" for i in body["items"])
    assert all(i["reason_label"] for i in body["items"])

def test_verification_endpoint_conflict_409():
    b = _batch()
    view = client.get(f"/api/supplement/{b['id']}").json()
    key = next(i["item_key"] for i in view["items"] if i["status"] == "待查")
    ok = client.post(f"/api/supplement/{b['id']}/verification",
                     json={"revision": view["revision"], "item_key": key,
                           "conclusion": "missing", "reviewer": "甲"})
    assert ok.status_code == 200
    stale = client.post(f"/api/supplement/{b['id']}/verification",
                        json={"revision": view["revision"], "item_key": key,
                              "conclusion": "held", "reviewer": "乙"})
    assert stale.status_code == 409 and stale.json()["error"] == "STALE"

def test_order_endpoint_releases_confirmed_while_pending_held():
    b = _batch()
    view = client.get(f"/api/supplement/{b['id']}").json()
    key = next(i["item_key"] for i in view["items"] if i["status"] == "待查")
    # 待查未处理也能开单，但只含确缺期，待查第2期被排除
    first = client.post(f"/api/supplement/{b['id']}/orders")
    assert first.status_code == 200
    assert [ln["issue"] for ln in first.json()["lines"]] == ["11"]
    # 核验为在馆后重试：单号不变、仍无第2期
    client.post(f"/api/supplement/{b['id']}/verification",
                json={"revision": view["revision"], "item_key": key,
                      "conclusion": "held", "reviewer": "乙"})
    second = client.post(f"/api/supplement/{b['id']}/orders")
    assert second.status_code == 200 and second.json()["order_no"] == first.json()["order_no"]
    assert "2" not in {ln["issue"] for ln in second.json()["lines"]}

def test_order_endpoint_idempotent():
    b = _batch()
    view = client.get(f"/api/supplement/{b['id']}").json()
    key = next(i["item_key"] for i in view["items"] if i["status"] == "待查")
    client.post(f"/api/supplement/{b['id']}/verification",
                json={"revision": view["revision"], "item_key": key,
                      "conclusion": "missing", "reviewer": "甲"})
    first = client.post(f"/api/supplement/{b['id']}/orders")
    second = client.post(f"/api/supplement/{b['id']}/orders")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["order_no"] == second.json()["order_no"]
    assert second.json()["idempotent"] is True

def test_supplement_view_unknown_404():
    assert client.get("/api/supplement/nonexistent0000").status_code == 404
