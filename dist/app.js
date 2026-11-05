// Renders dist/data/lab.json (built by src/build_lab.py). No dependencies.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const pct = (n) => (n === null ? "–" : `${Math.round(n * 100)}%`);
const isTron = (a) => /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a);

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
let lab;
let selected = null;
const decisions = {}; // alert_id -> { outcome, rationale }; kept in memory only

// Real addresses link to a block explorer; synthetic ones are labeled instead.
function addressLink(address, source) {
  if (source === "synthetic") return `<span class="mono">${esc(address)}</span> <span class="tag">synthetic</span>`;
  const url = isTron(address) ? `https://tronscan.org/#/address/${address}` : `https://etherscan.io/address/${address}`;
  return `<a class="mono" href="${url}" target="_blank" rel="noopener">${esc(address)}</a>`;
}

function renderHeader() {
  const s = lab.snapshot;
  $("#provenance").textContent = `Public data snapshot ${s.retrieved_at.slice(0, 10)}: ${s.counts.sanctioned_addresses} OFAC-listed crypto addresses, `
    + `${s.counts.tron_transfers.toLocaleString()} real USDT transfers of ${s.counts.tron_addresses_queried} sanctioned Tron wallets, `
    + `CoinGecko prices (USDT ${usd(lab.prices.tether.usd)}, ETH ${usd(lab.prices.ethereum.usd)}).`;
  const realCounterparties = new Set(lab.transfers.filter((t) => t.counterparty_source !== "synthetic").map((t) => t.counterparty_address));
  const kpis = [
    [lab.counts.alerts, "alerts"],
    [new Set(lab.alerts.map((a) => a.customer_id)).size, `of ${lab.counts.customers} customers alerted`],
    [lab.alerts.filter((a) => a.severity === "critical").length, "critical (direct sanctions)"],
    [realCounterparties.size, "real on-chain counterparties"],
  ];
  $("#kpis").innerHTML = kpis.map(([n, label]) => `<div class="kpi"><strong data-count="${n}">${n}</strong><span>${esc(label)}</span></div>`).join("");
  if (!reducedMotion) document.querySelectorAll("[data-count]").forEach(countUp);
}

// Counts a KPI up from zero; the final number is already in the markup for screen readers and no-JS fallbacks.
function countUp(el) {
  const target = Number(el.dataset.count);
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / 900);
    el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function renderMetrics() {
  $("#metrics").innerHTML = `<thead><tr><th>Rule</th><th class="num">Alerts</th><th class="num">Precision</th><th class="num">Recall</th><th>False positives</th></tr></thead><tbody>`
    + lab.metrics.map((m) => `<tr><td><b>${m.rule_id}</b> ${esc(m.title)}</td><td class="num">${m.alerts}</td>`
      + `<td class="num">${bar(m.precision)}${pct(m.precision)}</td><td class="num">${bar(m.recall)}${pct(m.recall)}</td>`
      + `<td>${m.false_positive_customers.map((c) => `${c} <span class="tag">${esc(customer(c).segment.replace("_", " "))}</span>`).join(", ") || "None"}</td></tr>`).join("")
    + "</tbody>";
}

const bar = (n) => `<span class="bar" aria-hidden="true"><i data-width="${Math.round((n ?? 0) * 100)}%"></i></span>`;
const customer = (id) => lab.customers.find((c) => c.customer_id === id);
const ruleTitle = (id) => lab.rules.find((r) => r.rule_id === id).title;

function renderQueue() {
  const sev = $("#f-severity").value;
  const rule = $("#f-rule").value;
  const rows = lab.alerts.filter((a) => (!sev || a.severity === sev) && (!rule || a.rule_id === rule));
  $("#queue-count").textContent = `${rows.length} of ${lab.alerts.length} alerts`;
  // Rows cascade in on first load only, not every time a filter or decision redraws the table.
  $("#alerts").innerHTML = `<thead><tr><th>Alert</th><th>Severity</th><th>Rule</th><th>Customer</th><th>Summary</th><th>Decision</th></tr></thead><tbody class="${$("#alerts tbody") ? "" : "cascade"}">`
    + rows.map((a, i) => `<tr data-id="${a.alert_id}" tabindex="0" aria-selected="${a.alert_id === selected}" style="--i:${i}">`
      + `<td>${a.alert_id}</td><td><span class="sev ${a.severity}">${a.severity}</span></td><td>${a.rule_id}</td>`
      + `<td>${a.customer_id}</td><td>${esc(a.summary)}</td><td>${esc(decisions[a.alert_id]?.outcome || "")}</td></tr>`).join("")
    + "</tbody>";
}

function evidenceRows(alert) {
  const e = alert.evidence;
  const tx = lab.transfers.find((t) => t.tx_id === alert.anchor_tx_id);
  const rows = [];
  if (e.counterparty) rows.push(["Other wallet", addressLink(e.counterparty, tx.counterparty_source)]);
  if (e.sdn_name) rows.push(["Sanctions list entry", `${esc(e.sdn_name)} (OFAC entry ${e.sdn_id}, program ${esc(e.program)}), listed as a ${esc(e.listed_asset)} address`]);
  if (e.example_tx_hash) {
    rows.push(["Its sanctions links", `${e.usdt_with_sanctioned.toLocaleString()} USDT over ${e.transfers_with_sanctioned} transfers with ${e.sanctioned_touched} sanctioned wallet${e.sanctioned_touched === 1 ? "" : "s"}, most recently ${e.last_seen.slice(0, 10)}`]);
    rows.push(["Biggest of those transfers", `<a class="mono" href="https://tronscan.org/#/transaction/${e.example_tx_hash}" target="_blank" rel="noopener">${e.example_tx_hash.slice(0, 18)}…</a> ${e.example_amount_usdt.toLocaleString()} USDT with ${addressLink(e.example_sanctioned_address, "ofac")}`]);
  }
  for (const [key, label] of [["deposit_usd", "Deposit"], ["withdrawn_usd", "Withdrawn"], ["dispersed_usd", "Dispersed"], ["total_usd", "Total"], ["withdrawal_usd", "Withdrawal"]])
    if (e[key] !== undefined) rows.push([label, usd(e[key])]);
  if (e.minutes_to_last_withdrawal !== undefined) rows.push(["Time to last withdrawal", `${e.minutes_to_last_withdrawal} minutes`]);
  if (e.new_addresses !== undefined) rows.push(["Wallets paid for the first time", e.new_addresses]);
  return rows;
}

function relatedTxIds(alert) {
  return new Set([alert.anchor_tx_id, ...(alert.evidence.withdrawal_tx_ids || [])]);
}

function renderDetail() {
  const alert = lab.alerts.find((a) => a.alert_id === selected);
  if (!alert) return;
  const c = customer(alert.customer_id);
  const related = relatedTxIds(alert);
  const txs = lab.transfers.filter((t) => t.customer_id === c.customer_id);
  const d = decisions[alert.alert_id] || {};
  const rule = lab.rules.find((r) => r.rule_id === alert.rule_id);
  $("#detail").innerHTML = `
    <p class="eyebrow">${alert.alert_id} · ${alert.rule_id} ${esc(ruleTitle(alert.rule_id))}</p>
    <h3>${esc(alert.summary)}</h3>
    <span class="sev ${alert.severity}">${alert.severity}</span>
    <p class="why"><b>Why this alerted:</b> ${esc(rule.plain)}</p>
    <h4>Customer</h4>
    <dl><dt>ID</dt><dd>${c.customer_id}</dd><dt>Segment</dt><dd>${esc(c.segment.replace("_", " "))}</dd>
      <dt>KYC risk</dt><dd>${c.kyc_risk}</dd><dt>Expected activity</dt><dd>${usd(c.expected_monthly_usd)} / month</dd>
      <dt>Customer since</dt><dd>${c.onboarded_at.slice(0, 10)}</dd></dl>
    <h4>Evidence</h4>
    <dl>${evidenceRows(alert).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <h4>Customer activity (${txs.length} transfers)</h4>
    <div class="table-scroll"><table><thead><tr><th>Time (UTC)</th><th>Direction</th><th class="num">USD</th><th>Other wallet</th><th>Recipient details</th></tr></thead><tbody>
      ${txs.map((t) => `<tr class="${related.has(t.tx_id) ? "related" : ""}"><td>${t.occurred_at.slice(5, 16)}</td><td>${t.direction}</td>`
        + `<td class="num">${usd(t.usd_value)}</td><td>${t.counterparty_source === "synthetic" ? `<span class="mono">${t.counterparty_address.slice(0, 10)}…</span>` : addressLink(t.counterparty_address, t.counterparty_source)}</td>`
        + `<td>${t.direction === "withdrawal" ? esc(t.beneficiary_name || "Missing") : ""}</td></tr>`).join("")}
    </tbody></table></div>
    <h4>What to check next</h4>
    <ul class="next">${rule.next_steps.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    <h4>Your decision</h4>
    <div class="actions" role="group" aria-label="Decision">
      ${["Escalate", "Request information", "Close: explained"].map((o) => `<button type="button" data-outcome="${o}" aria-pressed="${d.outcome === o}">${o}</button>`).join("")}
    </div>
    <label for="rationale" class="tag">Your reasoning: what supports the call, and what would change your mind</label>
    <textarea id="rationale">${esc(d.rationale || "")}</textarea>
    <div class="actions"><button type="button" class="primary" id="export">Download case summary</button><button type="button" id="reveal">Show answer key</button></div>
    <div id="answer"></div>`;
}

function caseSummary(alert) {
  const c = customer(alert.customer_id);
  const d = decisions[alert.alert_id] || {};
  const evidence = evidenceRows(alert).map(([k, v]) => `- ${k}: ${v.replace(/<[^>]+>/g, "")}`).join("\n");
  return `# Case summary: ${alert.alert_id}\n\n**Rule:** ${alert.rule_id} ${ruleTitle(alert.rule_id)}\n**Severity:** ${alert.severity}\n`
    + `**Customer:** ${c.customer_id} (${c.segment}, KYC risk ${c.kyc_risk}, expected ${usd(c.expected_monthly_usd)}/month)\n\n`
    + `## Alert\n${alert.summary}\n\n## Evidence\n${evidence}\n\n## Decision\n${d.outcome || "Not decided"}\n\n`
    + `## Rationale\n${d.rationale || "(none recorded)"}\n\n---\nFictional customer and ledger; addresses and on-chain links are public data. A lead for review, not a finding of wrongdoing.\n`;
}

function renderRules() {
  $("#f-rule").innerHTML += lab.rules.map((r) => `<option value="${r.rule_id}">${r.rule_id} ${esc(r.title)}</option>`).join("");
  const show = (id) => {
    document.querySelectorAll("#rule-tabs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rule === id)));
    const rule = lab.rules.find((r) => r.rule_id === id);
    $("#rule-plain").textContent = `In plain English: ${rule.plain}`;
    $("#rule-sql").textContent = rule.sql;
  };
  $("#rule-tabs").innerHTML = lab.rules.map((r) => `<button type="button" data-rule="${r.rule_id}">${r.rule_id} ${esc(r.title)}</button>`).join("");
  $("#rule-tabs").addEventListener("click", (e) => e.target.dataset.rule && show(e.target.dataset.rule));
  show(lab.rules[0].rule_id);
}

function select(id) {
  selected = id;
  renderQueue();
  renderDetail();
}

document.addEventListener("click", (e) => {
  const row = e.target.closest("#alerts tbody tr");
  if (row) return select(row.dataset.id);
  if (e.target.dataset.outcome) {
    decisions[selected] = { ...decisions[selected], outcome: e.target.dataset.outcome, rationale: $("#rationale").value };
    renderQueue();
    document.querySelectorAll("[data-outcome]").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target)));
  }
  if (e.target.id === "export") {
    const alert = lab.alerts.find((a) => a.alert_id === selected);
    const link = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(new Blob([caseSummary(alert)], { type: "text/markdown" })),
      download: `${alert.alert_id}-case-summary.md`,
    });
    link.click();
    URL.revokeObjectURL(link.href);
  }
  if (e.target.id === "reveal") {
    const c = customer(lab.alerts.find((a) => a.alert_id === selected).customer_id);
    $("#answer").innerHTML = `<div class="answer"><b>${c.seeded_typology ? `Risky behavior built in: ${esc(c.seeded_typology.replace(/_/g, " "))}` : "Nothing risky built in: this is a false positive"}</b><br>${esc(c.scenario)}</div>`;
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "rationale") decisions[selected] = { ...decisions[selected], rationale: e.target.value };
});
document.addEventListener("keydown", (e) => {
  const row = e.target.closest?.("#alerts tbody tr");
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(row.dataset.id); }
});
// Sections fade up as they scroll into view; metric bars fill when their table appears.
function observeReveals() {
  const fill = () => document.querySelectorAll(".bar i").forEach((b) => { b.style.width = b.dataset.width; });
  if (reducedMotion || !("IntersectionObserver" in window)) {
    document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
    return fill();
  }
  const io = new IntersectionObserver((entries) => entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add("in");
    if (entry.target.id === "performance") setTimeout(fill, 200);
    io.unobserve(entry.target);
  }), { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
}

$("#f-severity").addEventListener("change", renderQueue);
$("#f-rule").addEventListener("change", renderQueue);

fetch("data/lab.json")
  .then((r) => r.json())
  .then((data) => {
    lab = data;
    renderHeader();
    renderMetrics();
    renderRules();
    renderQueue();
    observeReveals();
  })
  .catch(() => { $("#provenance").textContent = "Could not load data/lab.json. Run python3 src/build_lab.py, then serve dist/."; });
