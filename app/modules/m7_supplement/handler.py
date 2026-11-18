from app.errors import object_payload, BusinessError
from fastapi import APIRouter, Body
from app.modules.m7_supplement.service import execute
from app import store
router = APIRouter()

@router.post("/api/7")
def calculate(payload: object = Body(default=None)):
    payload = object_payload(payload)
    from app.pipeline import sample_text
    text = payload.get("text", sample_text())
    if not isinstance(text, str):
        raise BusinessError("TEXT", "输入须为文本")
    return execute(text)

@router.get("/api/7")
def sample():
    from app.pipeline import sample_text
    return execute(sample_text())

@router.get("/api/supplement/{ident}")
def supplement_view(ident: str):
    """补录复核页面数据源：逐项可查为何待查或可开单。"""
    return store.review_view(ident)

@router.post("/api/supplement/{ident}/verification")
def verification(ident: str, payload: object = Body(...)):
    """实物核验结论提交；并发相反结论走乐观锁，后到者 409，不混用两份结论。"""
    payload = object_payload(payload)
    return store.submit_verification(
        ident, payload.get("revision"), str(payload.get("item_key", "")),
        payload.get("conclusion"), str(payload.get("reviewer", "")))

@router.post("/api/supplement/{ident}/orders")
def create_order(ident: str):
    """生成补录单；重试返回同一单号，不重复开单。"""
    return store.create_order(ident)
