// 补录复核：逐项展示待查/可开单原因，实物核验走乐观锁，重试开单不重复
(function () {
  const panel = document.getElementById("review-panel");
  if (!panel) return;
  const body = document.getElementById("review-body");
  const runId = body.dataset.run;
  const stateEl = document.getElementById("catalog-state");
  const state = JSON.parse(stateEl.textContent);
  const message = document.getElementById("review-message");
  const kpiPending = document.getElementById("kpi-pending");
  const kpiOrderable = document.getElementById("kpi-orderable");

  async function call(url, method, data) {
    const reply = await fetch(url, {
      method: method || "GET",
      headers: { "Content-Type": "application/json" },
      body: data ? JSON.stringify(data) : undefined,
    });
    const payload = await reply.json();
    if (!reply.ok) throw new Error(payload.message || "请求失败");
    return payload;
  }

  function render(view) {
    state.revision = view.revision;
    stateEl.textContent = JSON.stringify(state);
    body.innerHTML = "";
    let pending = 0, orderable = 0;
    for (const item of view.items) {
      if (item.status === "待查") pending += 1;
      if (item.orderable) orderable += 1;
      const card = document.createElement("div");
      const tone = item.status === "待查" ? "pending" : item.orderable ? "ok" : "muted";
      card.className = "task task-" + tone;
      card.dataset.item = item.item_key;
      const claimantText = item.evidence && item.evidence.claimants && item.evidence.claimants.length
        ? "冲突装订：" + item.evidence.claimants.map(c => c.binding + "(行" + c.line + ")").join(" / ")
        : "";
      card.innerHTML =
        "<b>" + item.issue + "<small>期</small></b>" +
        "<div>" + item.title +
        "<span>" + item.year + " / " + item.issn + (item.copy ? " / 复本" + item.copy : "") + "</span>" +
        '<em class="state state-' + item.status + '">' + item.status + " · " + item.reason_label + "</em>" +
        (claimantText ? '<small class="claimants">' + claimantText + "</small>" : "") +
        (item.status === "待查"
          ? '<div class="verify">' +
            '<button class="btn mini" data-conclusion="held">实物在馆</button> ' +
            '<button class="btn mini fill" data-conclusion="missing">实物确缺</button></div>'
          : "") +
        "</div>";
      body.appendChild(card);
    }
    if (!view.items.length) body.innerHTML = '<p class="empty">常规期次已齐。</p>';
    kpiPending.textContent = pending;
    kpiOrderable.textContent = orderable;
    message.textContent = view.blocked
      ? "冲突待复核：挂起期次按实物结论处理后再开单"
      : view.order ? "补录单 " + view.order.order_no + " 已生成（重试不重复开单）" : "可开单项已就绪";
    bindVerify(view);
  }

  function bindVerify(view) {
    body.querySelectorAll("[data-conclusion]").forEach(btn => {
      btn.onclick = async () => {
        const card = btn.closest(".task");
        const reviewer = (window.prompt && window.prompt("核验人姓名", "")) || "";
        if (!reviewer.trim()) { message.textContent = "需填写核验人"; return; }
        btn.disabled = true;
        try {
          await call("/api/supplement/" + runId + "/verification", "POST", {
            revision: view.revision,
            item_key: card.dataset.item,
            conclusion: btn.dataset.conclusion,
            reviewer: reviewer.trim(),
          });
          render(await call("/api/supplement/" + runId));
        } catch (err) {
          message.textContent = err.message + "；请刷新后以最新结论为准";
          btn.disabled = false;
        }
      };
    });
  }

  document.getElementById("open-order").onclick = async () => {
    try {
      const order = await call("/api/supplement/" + runId + "/orders", "POST");
      const view = await call("/api/supplement/" + runId);
      render(view);
      const held = (order.idempotent ? "复用既有补录单（不重复开单）：" : "补录单已生成：") +
        order.order_no + "，共 " + order.lines.length + " 项";
      message.textContent = held +
        (order.excluded_pending && order.excluded_pending.length
          ? "；另有 " + order.excluded_pending.length + " 个待查期挂起，查清前不入单"
          : "");
    } catch (err) {
      message.textContent = err.message;
    }
  };

  // 初次进入即拉取含核验历史与原因说明的复核视图
  call("/api/supplement/" + runId).then(render).catch(err => { message.textContent = err.message; });
})();
