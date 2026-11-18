# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；存在未处理的装订待查或刊名身份阻断项时不能通过。

补录复核（M7 配套）：

- `GET /api/supplement/{id}`：补录复核视图。逐项返回 status（确缺/待查/停刊/在馆）、reason、reason_label、orderable 与双侧装订证据、核验历史，页面据此解释每项为何待查或可开单。
- `POST /api/supplement/{id}/verification`：{"revision":整数,"item_key":"ISSN|年度|复本|期","conclusion":"held|missing","reviewer":"姓名"}。实物核验结论。revision 走乐观锁：两人同时提交相反结论时后到者 409(STALE)，结论不混用；不属于本批次缺期/冲突范围的 item_key 返回 404。
- `POST /api/supplement/{id}/orders`：按当前可开单项生成补录单，只放行确缺期，待查/停刊/实物在馆期不入单。同批次重试复用同一单号（idempotent=true），不重复开单；挂起期查清后再次调用会把新可开单项追加到原单，已分配行号不变。没有可开单项返回 422(NO_ORDERABLE)。

`GET /api/export/{id}`：唯一证据CSV，含 manifest、补录逐项结果、verification 核验结论、supplement_order 补录单与隔离记录。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
