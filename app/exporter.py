import csv, io, json
from app import store

def evidence_csv(run):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["run_id", "sha256", "rule_version", "kind", "line", "reason", "evidence"])
    writer.writerow([run["id"], run["digest"], run["rule_version"], "manifest", "", "",
                     json.dumps({"balance": run["result"]["balance"], "decision": run["decision"],
                                 "revision": run["revision"]}, ensure_ascii=False)])
    for row in run["result"].get("final", []):
        writer.writerow([run["id"], run["digest"], run["rule_version"], "result",
                         row.get("line", ""), row.get("reason", row.get("status", "")),
                         json.dumps(row, ensure_ascii=False)])
    try:
        for v in store.list_verifications(run["id"]):
            writer.writerow([run["id"], run["digest"], run["rule_version"], "verification", "",
                             v["conclusion"], json.dumps(v, ensure_ascii=False)])
        order = store.get_order(run["id"])
        if order:
            writer.writerow([run["id"], run["digest"], run["rule_version"], "supplement_order", "",
                             order["order_no"], json.dumps(order, ensure_ascii=False)])
    except Exception:
        pass
    for row in run["result"].get("quarantine", []):
        writer.writerow([run["id"], run["digest"], run["rule_version"], "quarantine",
                         row.get("line", ""), row["reason"], json.dumps(row, ensure_ascii=False)])
    return "﻿" + out.getvalue()
