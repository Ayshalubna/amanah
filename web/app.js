/* Amanah web app — plain JavaScript, no build step, works offline. */
(() => {
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const aed = n => "AED " + Math.round(n).toLocaleString("en-US");
const num = n => Math.round(n).toLocaleString("en-US");
const pct = x => Math.round(x * 100) + "%";
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(path, opts = {}) {
  const res = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ---------- plain-English dictionaries ---------- */
const REC = {
  clear: {c: "green", t: "All clear", d: "Nothing suspicious was found. The customer can be approved."},
  request_information: {c: "amber", t: "Ask for documents", d: "Something on the ID needs fixing — for example an expired card or a name that doesn't match. Ask the customer for updated documents before continuing."},
  enhanced_due_diligence: {c: "amber", t: "Take a closer look", d: "The money pattern is unusual but not clearly criminal. Review this customer more carefully and ask where the money comes from."},
  escalate_str_review: {c: "red", t: "Escalate: possible money laundering", d: "The transactions match known money-laundering patterns. Send this case to the Money Laundering Reporting Officer, who may file a report with the UAE Financial Intelligence Unit."},
  investigate_possible_match: {c: "red", t: "Check the name match", d: "This name is very similar to someone on a sanctions list. Confirm whether it is the same person (date of birth, passport) before doing anything else."},
  freeze_and_report: {c: "red", t: "Freeze & report", d: "This customer is very likely a person on a sanctions list. The law requires freezing their money immediately and reporting it to the authorities."},
};
const WATCH = {
  no_match: {c: "green", t: "Not on any banned list"},
  possible_match: {c: "amber", t: "Similar name on a banned list"},
  likely_match: {c: "red", t: "Very likely on a banned list"},
};
const RISK = {low: {c: "green", t: "Low"}, medium: {c: "amber", t: "Medium"}, high: {c: "red", t: "High"}};
const KYC = {pass: {c: "green", t: "ID card is valid"}, review: {c: "amber", t: "ID card needs a second look"}, fail: {c: "red", t: "Problem with the ID card"}};
const COLOR = {green: "var(--green)", amber: "#e59a12", red: "var(--red)"};
const LISTS = {"SAMPLE-UNSC": "UN Security Council sanctions", "SAMPLE-LOCAL-TERRORIST-LIST": "UAE local terrorist", "SAMPLE-PEP": "politically exposed persons (PEP)"};
const listName = l => LISTS[l] || String(l || "").replace(/-/g, " ").toLowerCase();
const hitWhy = h => [`name similarity ${Math.round(h.name_score)}/100`,
  h.dob_match === true ? "date of birth matches" : h.dob_match === false ? "date of birth is different" : "no date of birth to compare",
  h.nationality_match === true ? "nationality matches" : h.nationality_match === false ? "nationality is different" : ""].filter(Boolean).join(", ");
const badge = (c, t) => `<span class="badge b-${c}">${esc(t)}</span>`;
const riskBar = (score, level) => {
  const c = RISK[level].c;
  return `<div class="riskbar"><div class="track"><div class="fill" style="width:${Math.max(3, score * 100)}%;background:${COLOR[c]}"></div></div><b>${pct(score)}</b></div>`;
};

/* ---------- ticker + nav ---------- */
const TICK = ["<b>Amanah</b> AML & KYC copilot", "Arabic ⇄ English name matching", "Sanctions screening in seconds",
  "Spots money-laundering patterns", "Explains every answer in plain English", "A human approves every decision", "All demo data is synthetic"];
$("#ticker").innerHTML = [...TICK, ...TICK].map(t => `<span>${t}<span class="dot"></span></span>`).join("");
window.addEventListener("scroll", () => $("#nav").classList.toggle("scrolled", scrollY > 10));
$("#menu-btn").onclick = () => $("#links").classList.toggle("open");

function setActive(r) {
  $$(".links a").forEach(a => a.classList.toggle("active", a.dataset.r === r));
  $("#links").classList.remove("open");
}

function observe() {
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), {threshold: .12});
  $$(".reveal").forEach(el => io.observe(el));
}

function countUp(el) {
  const target = +el.dataset.to, t0 = performance.now(), dur = 1400;
  const step = now => {
    const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = num(target * e);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const loading = (txt = "Loading…") => `<div class="loading"><div class="spinner"></div>${esc(txt)}</div>`;

/* ================= HOME ================= */
async function home() {
  setActive("home");
  const title = "AMANAH".split("").map((ch, i) => `<span style="animation-delay:${.08 * i + .1}s">${ch}</span>`).join("");
  app.innerHTML = `<div class="page">
  <section class="hero">
    <div class="eyebrow reveal">Anti-money-laundering copilot · Built for UAE banks</div>
    <h1 class="mega" aria-label="Amanah">${title}</h1>
    <div class="hero-ar ar reveal" style="text-align:center;direction:rtl">أمانة — الثقة</div>
    <p class="lead reveal">An AI assistant that checks bank customers for <b>money laundering</b> and <b>sanctions</b> — in Arabic and English — and explains every answer in plain language. A person always makes the final decision.</p>
    <div class="hero-actions reveal">
      <a class="btn btn-dark" href="#/customers">Browse customers <span class="arrow">→</span></a>
      <a class="btn btn-line" href="#/check">Check a name</a>
      <a class="btn btn-line" href="#/help">How it works</a>
    </div>
  </section>

  <section class="showcase reveal">
    <div class="show-head">
      <div><h2>Try it in one click</h2><p>Pick an example customer. The AI agents will investigate and show you exactly what they found and why.</p></div>
    </div>
    <div class="examples" id="examples">${[1,2,3].map(() => `<div class="ex"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:70%"></div></div>`).join("")}</div>
  </section>

  <section class="stats" id="stats">
    ${["Bank customers", "Transactions", "Names on the banned list", "Customers the AI flags as high risk"].map(l => `<div class="stat reveal"><div class="n" data-to="0">0</div><div class="l">${l}</div></div>`).join("")}
  </section>

  <section class="section">
    <h2 class="section-title reveal">How it works</h2>
    <p class="section-sub reveal">Four AI agents do the checking work a compliance investigator normally does by hand — in seconds. Then you decide.</p>
    <div class="steps">
      ${[
        ["ID check", "Reads the Emirates ID in Arabic and English. Is the number real? Is it expired? Do the names match?"],
        ["Banned-list check", "Compares the name with sanctions lists — even when it is spelled differently or written in Arabic."],
        ["Money check", "Studies every bank transaction and scores how risky the pattern is, with reasons."],
        ["Report writer", "Reads the bank's rules and writes a short case report with a recommendation."],
        ["You decide", "Approve, reject or escalate. Nothing happens without a person. Every step is recorded."]
      ].map(([h, p], i) => `<div class="step reveal" style="transition-delay:${i * .08}s"><div class="num">${i + 1}</div><h4>${h}</h4><p>${p}</p></div>`).join("")}
    </div>
  </section>

  <section class="section">
    <div class="callout reveal">
      <div class="ic">ⓘ</div>
      <div><h3>Is this real data?</h3>
      <p>No — and that is on purpose. Real bank customer data is private and no bank shares it. Amanah creates <b>3,000 realistic but made-up customers</b>, their bank transactions and a made-up sanctions list, so you can see exactly how the system behaves. The same code can load the real public UN sanctions list.</p></div>
    </div>
  </section>
  </div>`;
  observe();

  const [stats, ex] = await Promise.all([api("/api/stats"), api("/api/examples")]);
  const vals = [stats.customers, stats.transactions, stats.watchlist, stats.high_risk];
  $$("#stats .n").forEach((el, i) => { el.dataset.to = vals[i]; countUp(el); });
  const cards = [
    ["sanctions", "t-red", "Sanctions example", "Someone on a banned list", "Their name is spelled differently from the list — watch the AI still catch it."],
    ["suspicious", "t-amber", "Money-laundering example", "Suspicious money movements", "A customer whose bank activity matches known laundering tricks."],
    ["clean", "t-green", "Normal example", "A regular, honest customer", "See what a clean result looks like — no false alarms."],
  ];
  $("#examples").innerHTML = cards.filter(c => ex[c[0]]).map(([k, cls, tag, h, p]) =>
    `<a class="ex" href="#/customer/${ex[k].id}?run=1"><span class="tag ${cls}">${tag}</span><h3>${h}</h3><p>${p}<br><br><b style="color:#fff">${esc(ex[k].name)}</b> · ${ex[k].id}</p><span class="go">Investigate <span class="arrow">→</span></span></a>`).join("");
}

/* ================= CUSTOMERS ================= */
const custState = {q: "", risk: "", watch: "", sort: "risk", page: 1};
async function customers() {
  setActive("customers");
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>Customers</h1><p>3,000 bank customers (synthetic). The AI has already given each one a <b>risk score</b> and checked their name against the <b>banned list</b>. Click any customer to see their details and investigate.</p></div></div>
    <div class="toolbar">
      <label class="search"><span>🔍</span><input id="q" placeholder="Search by name (English or Arabic), ID, country or job…" value="${esc(custState.q)}"></label>
      <select class="sel" id="sort" aria-label="Sort">
        <option value="risk">Sort: riskiest first</option><option value="name">Sort: name A–Z</option><option value="income">Sort: highest income</option>
      </select>
    </div>
    <div class="toolbar chips" id="filters">
      ${[["", "", "Everyone"], ["high", "", "High risk"], ["medium", "", "Medium risk"], ["low", "", "Low risk"], ["", "hit", "On a banned list"]]
        .map(([r, w, t]) => `<button class="chip" data-risk="${r}" data-watch="${w}">${t}</button>`).join("")}
    </div>
    <div class="table-card" id="tbl">${loading("Loading customers…")}</div>
  </div>`;
  $("#sort").value = custState.sort;
  const markChips = () => $$("#filters .chip").forEach(b => b.classList.toggle("on", b.dataset.risk === custState.risk && b.dataset.watch === custState.watch));
  markChips();
  $$("#filters .chip").forEach(b => b.onclick = () => { custState.risk = b.dataset.risk; custState.watch = b.dataset.watch; custState.page = 1; markChips(); loadCustomers(); });
  let t; $("#q").oninput = e => { clearTimeout(t); t = setTimeout(() => { custState.q = e.target.value; custState.page = 1; loadCustomers(); }, 220); };
  $("#sort").onchange = e => { custState.sort = e.target.value; custState.page = 1; loadCustomers(); };
  loadCustomers();
}

async function loadCustomers() {
  const s = custState;
  const data = await api(`/api/customers?q=${encodeURIComponent(s.q)}&risk=${s.risk}&watch=${s.watch}&sort=${s.sort}&page=${s.page}&size=20`);
  const pages = Math.max(1, Math.ceil(data.total / data.size));
  if (!data.rows.length) { $("#tbl").innerHTML = `<div class="empty">No customers match. Try a different search.</div>`; return; }
  $("#tbl").innerHTML = `<table>
    <thead><tr><th>Customer</th><th class="hide-sm">Country</th><th class="hide-sm">Type · Job</th><th class="hide-sm">Monthly income</th><th>Money risk</th><th>Banned list</th></tr></thead>
    <tbody>${data.rows.map(r => `<tr class="clickable" data-id="${r.id}">
      <td class="name">${esc(r.name_en)}${r.name_ar ? `<span class="ar">${esc(r.name_ar)}</span>` : ""}<span class="muted" style="font-weight:500;font-size:13px">${r.id}</span></td>
      <td class="hide-sm">${esc(r.nationality)}</td>
      <td class="hide-sm">${esc(r.segment)} · ${esc(r.occupation)}</td>
      <td class="hide-sm">${aed(r.income)}</td>
      <td>${badge(RISK[r.risk_level].c, RISK[r.risk_level].t)}${riskBar(r.risk, r.risk_level)}</td>
      <td>${badge(WATCH[r.watchlist].c, WATCH[r.watchlist].t)}</td></tr>`).join("")}</tbody></table>
    <div class="pager"><span>Showing ${num((s.page - 1) * data.size + 1)}–${num(Math.min(s.page * data.size, data.total))} of ${num(data.total)}</span>
    <div class="btns"><button id="prev" ${s.page <= 1 ? "disabled" : ""}>← Previous</button><button id="next" ${s.page >= pages ? "disabled" : ""}>Next →</button></div></div>`;
  $$("#tbl tr.clickable").forEach(tr => tr.onclick = () => location.hash = `#/customer/${tr.dataset.id}`);
  $("#prev").onclick = () => { s.page--; loadCustomers(); scrollTo({top: 0, behavior: "smooth"}); };
  $("#next").onclick = () => { s.page++; loadCustomers(); scrollTo({top: 0, behavior: "smooth"}); };
}

/* ================= CUSTOMER PROFILE + INVESTIGATION ================= */
function txChart(txs) {
  if (!txs.length) return `<div class="empty">No transactions.</div>`;
  const W = 1000, H = 260, P = 34;
  const times = txs.map(t => new Date(t.date.replace(" ", "T")).getTime());
  const t0 = Math.min(...times), t1 = Math.max(...times) || t0 + 1;
  const max = Math.max(...txs.map(t => t.amount));
  const inbound = new Set(["transfer_in", "cash_in"]);
  const bars = txs.map((t, i) => {
    const x = P + ((times[i] - t0) / Math.max(1, t1 - t0)) * (W - 2 * P);
    const h = Math.max(3, Math.sqrt(t.amount / max) * (H / 2 - 20));
    const up = inbound.has(t.kind);
    const col = t.flags.length ? "var(--red)" : up ? "#1c1c1c" : "#b9b9b3";
    const y = up ? H / 2 - h : H / 2;
    return `<rect class="bar" x="${x - 2.5}" y="${y}" width="5" height="${h}" rx="2" fill="${col}"><title>${esc(t.date)} · ${esc(t.type)} · ${aed(t.amount)}${t.flags.length ? " · ⚠ " + esc(t.flags.join("; ")) : ""}</title></rect>`;
  }).join("");
  const d = ts => new Date(ts).toLocaleDateString("en-GB", {day: "numeric", month: "short"});
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Transactions over time">
    <line x1="${P}" x2="${W - P}" y1="${H / 2}" y2="${H / 2}" stroke="#d6d6d1"/>
    <text x="${P}" y="14" font-size="12" fill="#6f6f6b" font-weight="700">▲ MONEY IN</text>
    <text x="${P}" y="${H - 4}" font-size="12" fill="#6f6f6b" font-weight="700">▼ MONEY OUT</text>
    <text x="${W - P}" y="14" font-size="12" fill="#6f6f6b" text-anchor="end">tallest bar = ${aed(max)}</text>
    ${bars}
    <text x="${P}" y="${H / 2 + 16}" font-size="11" fill="#9b9b95">${d(t0)}</text>
    <text x="${W - P}" y="${H / 2 + 16}" font-size="11" fill="#9b9b95" text-anchor="end">${d(t1)}</text>
  </svg>`;
}

async function customer(id, autorun) {
  setActive("customers");
  app.innerHTML = `<div class="page">${loading("Loading customer…")}</div>`;
  let c;
  try { c = await api(`/api/customers/${id}`); } catch (e) { app.innerHTML = `<div class="page empty">Customer not found. <a href="#/customers"><u>Back to customers</u></a></div>`; return; }
  const flagged = c.transactions.filter(t => t.flags.length);
  app.innerHTML = `<div class="page">
    <a class="back" href="#/customers">← All customers</a>
    <div class="profile-top" style="margin-top:18px">
      <div class="card who reveal">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">${badge(RISK[c.risk_level].c, "Money risk: " + RISK[c.risk_level].t)}${badge(WATCH[c.watchlist].c, WATCH[c.watchlist].t)}</div>
        <h2>${esc(c.name_en)}</h2>${c.name_ar ? `<span class="ar">${esc(c.name_ar)}</span>` : "<div style='height:14px'></div>"}
        <div class="facts">
          <div><span>Customer ID</span><b>${c.id}</b></div><div><span>Nationality</span><b>${esc(c.nationality)}</b></div>
          <div><span>Date of birth</span><b>${c.dob}</b></div><div><span>Customer type · Job</span><b>${esc(c.segment)} · ${esc(c.occupation)}</b></div>
          <div><span>Emirates ID</span><b>${c.emirates_id}</b></div><div><span>ID expires</span><b>${c.id_expiry}</b></div>
          <div><span>Declared monthly income</span><b>${aed(c.income)}</b></div><div><span>AI money-risk score</span><b>${pct(c.risk)}</b></div>
        </div>
      </div>
      <div class="card reveal">
        <h3>Money in the last 90 days</h3>
        <div class="mini-stats">
          <div class="mini"><div class="n">${num(c.summary.transactions)}</div><div class="l">Transactions</div></div>
          <div class="mini"><div class="n" style="color:${c.summary.flagged ? "var(--red)" : "inherit"}">${num(c.summary.flagged)}</div><div class="l">Look unusual</div></div>
          <div class="mini"><div class="n">${aed(c.summary.money_in)}</div><div class="l">Money in</div></div>
          <div class="mini"><div class="n">${aed(c.summary.money_out)}</div><div class="l">Money out</div></div>
        </div>
      </div>
    </div>

    <div class="card reveal" style="margin-bottom:18px">
      <h3>Every transaction <small>hover a bar for details</small></h3>
      <div class="chart-wrap">${txChart(c.transactions)}</div>
      <div class="legend"><span><i style="background:#1c1c1c"></i>Money in</span><span><i style="background:#b9b9b3"></i>Money out</span><span><i style="background:var(--red)"></i>Looks unusual</span></div>
    </div>

    <div class="card reveal" style="margin-bottom:18px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
        <h3 style="margin:0">Transaction list</h3>
        <label class="toggle"><input type="checkbox" id="only" ${flagged.length ? "checked" : ""}> Only show unusual ones (${flagged.length})</label>
      </div>
      <div class="scroll-y" id="txlist"></div>
    </div>

    <section class="investigate reveal" id="inv">
      <h2>Ask the AI agents to investigate</h2>
      <p class="sub">Four agents will check this customer one after another. It takes a few seconds. You make the final decision.</p>
      <button class="btn btn-yellow" id="run">Start investigation <span class="arrow">→</span></button>
      <div id="inv-body"></div>
    </section>
  </div>`;
  observe();
  const renderTx = only => {
    const list = only ? flagged : c.transactions;
    $("#txlist").innerHTML = list.length ? `<table><thead><tr><th>Date</th><th>What</th><th>Amount</th><th class="hide-sm">Country</th><th>Why it looks unusual</th></tr></thead><tbody>
      ${list.slice().reverse().map(t => `<tr><td>${esc(t.date)}</td><td>${esc(t.type)}</td><td><b>${aed(t.amount)}</b></td><td class="hide-sm">${esc(t.country)}</td><td>${t.flags.length ? `<span class="flagtxt">⚠ ${esc(t.flags.join(" · "))}</span>` : `<span class="muted">—</span>`}</td></tr>`).join("")}
    </tbody></table>` : `<div class="empty">Nothing unusual in this customer's transactions.</div>`;
  };
  renderTx(!!flagged.length);
  $("#only").onchange = e => renderTx(e.target.checked);
  $("#run").onclick = () => investigate(c);
  if (autorun) { await sleep(700); $("#inv").scrollIntoView({behavior: "smooth", block: "start"}); await sleep(600); investigate(c); }
}

async function investigate(c) {
  $("#run").classList.add("hidden");
  const agents = [
    ["🪪", "ID check", "Reading the Emirates ID…"],
    ["🔎", "Banned-list check", "Comparing the name with sanctions lists…"],
    ["📈", "Money check", "Studying every transaction…"],
    ["📝", "Report writer", "Reading the bank's rules and writing the report…"],
  ];
  $("#inv-body").innerHTML = `<div class="pipeline">${agents.map(([ic, n, w], i) =>
    `<div class="agent" id="ag${i}"><div class="top"><div class="ic">${ic}</div><div><div class="name">${n}</div><div class="what">${w}</div></div></div><div class="result"></div></div>`).join("")}</div><div id="verdict"></div>`;
  const req = api("/cases", {method: "POST", body: JSON.stringify({customer_id: c.id})});
  let res;
  for (let i = 0; i < 4; i++) {
    $(`#ag${i}`).classList.add("active");
    await sleep(i === 3 ? 900 : 750);
    if (i === 0) { try { res = await req; } catch (e) { $("#inv-body").innerHTML = `<p class="r-red" style="margin-top:14px">Something went wrong: ${esc(e.message)}</p>`; $("#run").classList.remove("hidden"); return; } }
    const el = $(`#ag${i}`), out = $(".result", el);
    let txt, cls;
    if (i === 0) { const k = KYC[res.kyc.status]; txt = (res.kyc.status === "pass" ? "✓ " : "⚠ ") + k.t; cls = k.c; }
    if (i === 1) { const w = WATCH[res.screening.disposition]; txt = (res.screening.disposition === "no_match" ? "✓ " : "⚠ ") + w.t; cls = w.c; }
    if (i === 2) { const a = res.monitoring.alert; txt = `${a ? "⚠ Unusual activity" : "✓ Normal activity"} · risk ${pct(res.monitoring.risk_score)}`; cls = a ? "red" : "green"; }
    if (i === 3) { const r = REC[res.recommendation]; txt = "→ " + r.t; cls = r.c; }
    out.className = `result r-${cls}`; out.textContent = txt;
    if (i === 3 && !res.trace.some(t => t.agent === "case_agent")) $(".what", el).textContent = "No risk found, so the report writer was not needed.";
    el.classList.remove("active"); el.classList.add("done");
  }
  renderVerdict(c, res);
}

function renderVerdict(c, res) {
  const r = REC[res.recommendation], cs = res.case, k = res.kyc, s = res.screening, m = res.monitoring;
  const findings = [];
  k.issues.forEach(i => findings.push(`ID card: ${i.issue}`));
  if (s.hits.length && s.disposition !== "no_match") {
    const h = s.hits[0];
    findings.push(`The name matches <b>${esc(h.listed_name)}</b>${h.listed_name_ar ? ` (<span class="ar">${esc(h.listed_name_ar)}</span>)` : ""} on the <b>${esc(listName(h.list_name))}</b> list: ${esc(hitWhy(h))}. How sure: <b>${pct(h.confidence)}</b>.`);
  }
  m.indicators.forEach(i => findings.push(esc(i)));
  const nFlag = c.summary.flagged;
  if (nFlag && !m.indicators.length && m.alert) findings.push(`${nFlag} transactions look unusual — see the transaction list above.`);
  if (!findings.length) findings.push("Nothing unusual was found in the ID, the banned lists or the transactions.");
  const maxImpact = Math.max(...m.drivers.map(d => Math.abs(d.impact)), 0.001);
  const why = m.drivers.map(d => `<div class="row"><div>${esc(d.feature[0].toUpperCase() + d.feature.slice(1))} <span style="color:var(--panel-mute)">(${num(d.value)})</span> — <b class="${d.impact > 0 ? "r-red" : "r-green"}">${d.impact > 0 ? "raises" : "lowers"} risk</b></div>
    <div class="bar"><i style="width:${Math.abs(d.impact) / maxImpact * 100}%;background:${d.impact > 0 ? "var(--red)" : "var(--green)"}"></i></div></div>`).join("");
  $("#verdict").innerHTML = `
    <div class="verdict v-${r.c}"><div class="lbl">AI recommendation · case ${esc(res.case_id)}</div><h3>${r.t}</h3><p>${r.d}</p></div>
    <div class="detail-grid">
      <div class="dpanel"><h4>What the agents found</h4><ul>${findings.map(f => `<li><span>${f}</span></li>`).join("")}</ul></div>
      <div class="dpanel"><h4>Why the money check scored ${pct(m.risk_score)}</h4><div class="why">${why || "<p style='color:#bbb'>No transactions.</p>"}</div>
        <p class="cite">Bars show how much each factor pushed the risk up (red) or down (green). Measured with SHAP.</p></div>
    </div>
    <div class="dpanel" style="margin-top:14px"><h4>Case report</h4><p style="color:#e4e4df">${esc(cs.summary)}</p>
      ${cs.citations && cs.citations.length ? `<p class="cite">Bank rules used: ${cs.citations.map(esc).join(" · ")}</p>` : ""}
      <p class="cite">Written by: ${cs.drafted_by === "template" ? "built-in template (no AI model connected)" : esc(cs.drafted_by)}</p></div>
    <div class="decision" id="decision">
      <h4>Your decision</h4><p class="muted">The AI only recommends. Type your name, then approve, reject or escalate. This is saved to the audit record.</p>
      <div class="row"><input id="who" placeholder="Your name" value="${esc(localStorage.getItem("amanah_reviewer") || "")}"></div>
      <textarea id="note" placeholder="Optional note (for example: 'Called the customer, documents requested')"></textarea>
      <div class="row">
        <button class="btn btn-green" data-d="approve">✓ Approve recommendation</button>
        <button class="btn btn-red" data-d="reject">✕ Reject</button>
        <button class="btn btn-amber" data-d="escalate">↑ Escalate to senior officer</button>
      </div>
    </div>`;
  $("#verdict").scrollIntoView({behavior: "smooth", block: "start"});
  $$("#decision [data-d]").forEach(b => b.onclick = async () => {
    const who = $("#who").value.trim();
    if (who.length < 2) { $("#who").focus(); toast("Please type your name first"); return; }
    try { localStorage.setItem("amanah_reviewer", who); } catch (_) {}
    const out = await api(`/cases/${res.case_id}/review`, {method: "POST", body: JSON.stringify({decision: b.dataset.d, reviewer: who, note: $("#note").value})});
    const word = {approve: "approved", reject: "rejected", escalate: "escalated"}[out.decision];
    $("#decision").innerHTML = `<div class="done-box"><div class="tick">✓</div><div>Decision saved: ${word} by ${esc(out.reviewer)}.<br><a href="#/cases" style="text-decoration:underline;font-size:15px">See all decisions and the audit record →</a></div></div>`;
    toast("Decision saved to the audit record");
  });
}

/* ================= NAME CHECK ================= */
async function check() {
  setActive("check");
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>Name check</h1><p>Type any name — in English, Arabic or a different spelling — and see instantly whether it matches someone on the banned list. Adding a date of birth makes the check much more accurate.</p></div></div>
    <div class="check-grid">
      <div class="field"><label for="n-en">Name in English</label><input id="n-en" placeholder="e.g. Mohd Al-Mansoori" autocomplete="off"></div>
      <div class="field"><label for="n-ar">الاسم بالعربية</label><input id="n-ar" class="ar" style="text-align:right" placeholder="مثال: محمد المنصوري" autocomplete="off"></div>
      <div class="field"><label for="n-dob">Date of birth (optional)</label><input id="n-dob" type="date"></div>
    </div>
    <div class="try" id="try">Try:</div>
    <div id="check-out"><div class="card"><p class="muted">Results appear here as you type.</p></div></div>
  </div>`;
  const wl = await api("/api/watchlist");
  const tries = [];
  wl.slice(0, 3).forEach((e, i) => tries.push(i === 1 ? {ar: e.name_ar} : {en: (e.aliases[0] || e.name_en)}));
  tries.push({en: "John Carter"});
  $("#try").innerHTML = "Try:" + tries.map((t, i) => `<button class="chip" data-i="${i}">${esc(t.en || t.ar)}</button>`).join("");
  $$("#try .chip").forEach(b => b.onclick = () => { const t = tries[b.dataset.i]; $("#n-en").value = t.en || ""; $("#n-ar").value = t.ar || ""; run(); });
  let timer;
  const run = async () => {
    const en = $("#n-en").value.trim(), ar = $("#n-ar").value.trim(), dob = $("#n-dob").value || null;
    if (!en && !ar) { $("#check-out").innerHTML = `<div class="card"><p class="muted">Results appear here as you type.</p></div>`; return; }
    const r = await api("/screen", {method: "POST", body: JSON.stringify({name_en: en, name_ar: ar, dob})});
    const w = WATCH[r.disposition];
    const msg = {no_match: "No one on the banned list has this name. Safe to continue.",
      possible_match: "Someone on the banned list has a similar name. Check their date of birth and passport before continuing.",
      likely_match: "This is very likely a person on the banned list. Do not proceed — escalate immediately."}[r.disposition];
    $("#check-out").innerHTML = `<div class="result-big rb-${w.c}"><h3>${w.t}</h3><p style="margin-top:6px">${msg}</p></div>` +
      r.hits.map((h, i) => `<div class="hit" style="animation-delay:${i * .06}s"><div><h4>${esc(h.listed_name)} <span class="ar" style="font-weight:500;color:var(--mute)">${esc(h.listed_name_ar)}</span></h4>
        <p class="muted" style="font-size:14px;margin-top:4px">On the ${esc(listName(h.list_name))} list</p></div>
        <div><div style="display:flex;justify-content:space-between;font-weight:700;font-size:14px;margin-bottom:6px"><span>How sure</span><span>${pct(h.confidence)}</span></div>
        <div class="meter"><i style="width:${h.confidence * 100}%;background:${h.confidence >= .75 ? "var(--red)" : h.confidence >= .35 ? "#e59a12" : "#b9b9b3"}"></i></div>
        <p class="muted" style="font-size:12px;margin-top:6px">${esc(hitWhy(h))}</p></div></div>`).join("");
  };
  ["n-en", "n-ar", "n-dob"].forEach(id => $("#" + id).addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 200); }));
}

/* ================= WATCHLIST ================= */
async function watchlistPage() {
  setActive("watchlist");
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>Banned list</h1><p>The sanctions list the AI checks against: people the bank must not do business with. In this demo the ${""}60 names are made up. In real use, it would be the UN Security Council list and the UAE Local Terrorist List.</p></div></div>
    <div class="toolbar"><label class="search"><span>🔍</span><input id="wq" placeholder="Search the list (English or Arabic)…"></label></div>
    <div class="wl-grid" id="wl">${loading()}</div></div>`;
  const draw = async q => {
    const rows = await api(`/api/watchlist?q=${encodeURIComponent(q)}`);
    $("#wl").innerHTML = rows.length ? rows.map((e, i) => `<div class="wl" style="animation:pageIn .5s var(--ease) ${Math.min(i, 12) * .03}s both">
      <span class="badge b-grey" style="align-self:flex-start">${esc(e.list)}</span>
      <h4>${esc(e.name_en)}</h4><div class="ar">${esc(e.name_ar)}</div>
      <div class="aliases">${e.aliases.map(a => `<span>also: ${esc(a)}</span>`).join("")}</div>
      <div class="meta">Born ${esc(e.dob)} · ${esc(e.nationality)}</div><div class="meta">${esc(e.reason)}</div></div>`).join("") : `<div class="empty">No names match.</div>`;
  };
  let t; $("#wq").oninput = e => { clearTimeout(t); t = setTimeout(() => draw(e.target.value), 200); };
  draw("");
}

/* ================= DECISIONS ================= */
async function cases() {
  setActive("cases");
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>Decisions</h1><p>Every investigation and every decision is recorded — who decided, when, and what the AI recommended. Banks are legally required to keep this record. Click a row to see the full step-by-step history.</p></div></div>
    <div class="table-card" id="ctbl">${loading()}</div></div>`;
  const [rows, custs] = [await api("/cases"), null];
  if (!rows.length) { $("#ctbl").innerHTML = `<div class="empty">No investigations yet. <a href="#/customers"><u>Pick a customer</u></a> and click “Start investigation”.</div>`; return; }
  $("#ctbl").innerHTML = `<table><thead><tr><th>Case</th><th>Customer</th><th>AI recommended</th><th>Decision</th><th class="hide-sm">Decided by</th><th class="hide-sm">When</th></tr></thead><tbody>
    ${rows.map(r => { const rec = REC[r.recommendation] || {c: "grey", t: r.recommendation || "—"};
      const dec = r.decision ? badge({approve: "green", reject: "red", escalate: "amber"}[r.decision] || "grey", r.decision) : badge("grey", "waiting");
      return `<tr class="clickable" data-id="${esc(r.case_id)}"><td><b>${esc(r.case_id)}</b></td><td>${esc(r.customer_id)}</td><td>${badge(rec.c, rec.t)}</td><td>${dec}</td>
      <td class="hide-sm">${esc(r.reviewer || "—")}</td><td class="hide-sm">${esc((r.decided_at || r.created_at || "").replace("T", " ").slice(0, 16))}</td></tr>`; }).join("")}
  </tbody></table>`;
  $$("#ctbl tr.clickable").forEach(tr => tr.onclick = () => auditModal(tr.dataset.id));
}

async function auditModal(id) {
  const ev = await api(`/cases/${id}/audit`);
  const NAME = {kyc_agent: "ID check agent", screening_agent: "Banned-list agent", monitoring_agent: "Money check agent", supervisor: "Supervisor", case_agent: "Report writer", investigator: "Human decision"};
  const plain = a => a.replace("verified identity document (pass)", "ID card checked — valid").replace("verified identity document (review)", "ID card checked — needs a second look")
    .replace("verified identity document (fail)", "ID card checked — problem found").replace("screened against watchlists (no_match)", "Name checked — not on any banned list")
    .replace("screened against watchlists (possible_match)", "Name checked — similar name on a banned list").replace("screened against watchlists (likely_match)", "Name checked — very likely on a banned list")
    .replace(/scored transactions \(risk ([0-9.]+)\)/, (_, r) => `Transactions scored — risk ${Math.round(r * 100)}%`)
    .replace("route -> case_agent", "Risk found — sent to the report writer").replace("route -> human_review", "No risk found — sent straight to a person")
    .replace(/drafted case \((\w+)\)/, (_, r) => `Report written — recommends: ${(REC[r] || {t: r}).t}`)
    .replace(/^approve \((.*)\)$/, "Approved by $1").replace(/^reject \((.*)\)$/, "Rejected by $1").replace(/^escalate \((.*)\)$/, "Escalated by $1");
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal"><button class="x" aria-label="Close">×</button><h3 style="font-size:24px;margin-bottom:4px">${esc(id)}</h3><p class="muted" style="margin-bottom:18px">Full history, in order</p>
    <div class="timeline">${ev.map(e => `<div class="tl"><div class="dot" style="${e.agent === "investigator" ? "background:var(--accent)" : ""}"></div><div><b>${esc(NAME[e.agent] || e.agent)}</b><div>${esc(plain(e.action))}</div><span>${esc(e.ts.replace("T", " ").slice(0, 19))}${e.latency_ms ? ` · ${e.latency_ms} ms` : ""}</span></div></div>`).join("")}</div></div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  bg.onclick = e => { if (e.target === bg || e.target.classList.contains("x")) close(); };
  document.addEventListener("keydown", function k(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", k); } });
}

/* ================= ACCURACY ================= */
async function accuracy() {
  setActive("accuracy");
  app.innerHTML = `<div class="page">${loading()}</div>`;
  const r = await api("/api/eval");
  if (!r.screening) { app.innerHTML = `<div class="page empty">No accuracy results yet.</div>`; return; }
  const s = r.screening, m = r.monitoring, e = r.end_to_end;
  const bar = (label, v, col) => `<div class="r"><span>${label}</span><div class="t"><i style="width:${v * 100}%;background:${col}"></i></div><span class="v">${pct(v)}</span></div>`;
  const variants = {arabic_script: "Written in Arabic", arabic_with_diacritics: "Arabic with vowel marks", honorific: "With a title (Sheikh, Dr)", middle_name_dropped: "Middle name missing", mixed_script: "Half Arabic, half English", reordered: "Words in a different order", spelling_variant: "Different spelling", typo: "Typing mistake"};
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>How accurate is it?</h1><p>We tested Amanah on thousands of examples where we already knew the right answer, and compared it with simpler methods that banks often use. All tests use synthetic data.</p></div></div>
    <div class="acc-grid">
      <div class="card reveal"><h3>Catching banned people</h3><div class="big-num">${pct(s.amanah_full.recall)}</div>
        <p class="muted" style="margin:6px 0 14px">of disguised banned names caught, out of ${num(s.positives)} test names — while wrongly flagging only ${num(s.amanah_full.false_positives)} of ${num(s.test_cases - s.positives)} innocent people.</p>
        <div class="bars">${bar("Amanah", s.amanah_full.recall, "var(--ink)")}${bar("Simple fuzzy matching", s.baseline_plain_fuzzy.recall, "#b9b9b3")}${bar("Exact spelling only", s.baseline_exact.recall, "#d6d6d1")}</div></div>
      <div class="card reveal"><h3>Catching money laundering</h3><div class="big-num">${pct(m.model.recall)}</div>
        <p class="muted" style="margin:6px 0 14px">of suspicious customers caught by the AI model, out of ${num(m.suspicious_customers)} — compared with fixed rules that most banks use.</p>
        <div class="bars">${bar("Amanah AI model", m.model.recall, "var(--ink)")}${bar("Fixed rules", m.rules_baseline.recall, "#b9b9b3")}</div></div>
    </div>
    <div class="card reveal" style="margin-top:18px"><h3>Names written in tricky ways <small>share caught</small></h3>
      <div class="bars">${Object.entries(s.amanah_full.recall_by_variant).map(([k, v]) => `<div class="r"><span>${variants[k] || k}</span><div class="t" style="position:relative"><i style="width:${v * 100}%;background:var(--ink)"></i></div><span class="v">${pct(v)}</span></div>
        <div class="r" style="margin-top:-12px;font-weight:500;color:var(--mute);font-size:13px"><span>simple matching</span><div class="t" style="height:10px"><i style="width:${s.baseline_plain_fuzzy.recall_by_variant[k] * 100}%;background:#c9c9c3"></i></div><span class="v" style="font-weight:600">${pct(s.baseline_plain_fuzzy.recall_by_variant[k])}</span></div>`).join("")}</div></div>
    <div class="card reveal" style="margin-top:18px"><h3>Full system test</h3><p class="muted" style="margin-bottom:12px">${num(e.cases)} customers run through all four agents, using a model that had never seen them.</p>
      <div class="bars">${bar("Banned people flagged", e.e2e_watchlist_flagged, "var(--red)")}${bar("Suspicious customers escalated", e.e2e_suspicious_escalated, "#e59a12")}${bar("Honest customers cleared", e.e2e_clean_cleared, "var(--green)")}</div></div>
  </div>`;
  observe();
}

/* ================= HELP ================= */
function help() {
  setActive("help");
  const faq = [
    ["What is Amanah?", "An AI assistant for bank compliance teams. It checks customers for money laundering and sanctions (banned people), explains what it found in plain language, and lets a human make the final decision."],
    ["How do I use it?", "Go to <b>Customers</b>, click any customer, then press <b>Start investigation</b>. Read the recommendation and the reasons, type your name, and approve, reject or escalate. Or use <b>Name check</b> to test any name quickly."],
    ["Is the data real?", "No. Real bank data is private, so Amanah generates 3,000 realistic but made-up customers, about 124,000 transactions and a made-up banned list. The code can load the real public UN sanctions list."],
    ["Does the AI decide on its own?", "Never. The AI only recommends. It cannot freeze money, close a case or file a report. A person must approve every case, and every step is recorded on the Decisions page."],
    ["How does it catch names spelled differently?", "Arabic names can be written many ways in English (Mohammed, Muhammad, Mohd). Amanah converts every name into a common form, ignores vowels and titles, and then compares. It also checks the date of birth, so two different people with the same name are not confused."],
    ["What makes a transaction look unusual?", "Patterns criminals use: many cash deposits just under AED 55,000, money that comes in and goes straight out, transfers to high-risk countries, sudden large round amounts, or money far bigger than the person's income."],
    ["Is there an AI language model inside?", "Yes, optionally. If Ollama is installed on this computer, a free local AI model writes the case reports and reads ID cards. Without it, Amanah uses built-in templates, so everything still works."],
  ];
  const gloss = [
    ["AML", "Anti-Money Laundering — stopping criminals from making dirty money look clean."],
    ["KYC", "Know Your Customer — checking a customer's identity before opening an account."],
    ["Sanctions list", "An official list of people and companies banks must not deal with."],
    ["PEP", "Politically Exposed Person — someone in a public role who needs extra checks."],
    ["STR", "Suspicious Transaction Report — sent to the UAE Financial Intelligence Unit via goAML."],
    ["Structuring", "Splitting cash into many deposits just below the reporting limit to avoid notice."],
    ["Risk score", "The AI's estimate (0–100%) of how suspicious a customer's money activity is."],
    ["SHAP", "A method that shows which factors pushed the risk score up or down."],
    ["Audit trail", "A permanent record of every step and decision, required by regulators."],
  ];
  app.innerHTML = `<div class="page">
    <div class="phead"><div><h1>Help</h1><p>Everything you need to use Amanah, in plain language.</p></div></div>
    <div class="faq">${faq.map(([q, a], i) => `<details class="reveal" ${i < 2 ? "open" : ""}><summary>${q}</summary><p>${a}</p></details>`).join("")}</div>
    <div class="section"><h2 class="section-title reveal" style="font-size:44px">Words you'll see</h2>
    <div class="gloss">${gloss.map(([w, d]) => `<div class="reveal"><b>${w}</b><span>${d}</span></div>`).join("")}</div></div>
  </div>`;
  observe();
}

/* ================= router ================= */
async function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  scrollTo({top: 0});
  $$(".modal-bg").forEach(m => m.remove());
  try {
    if (!parts.length) return home();
    if (parts[0] === "customers") return customers();
    if (parts[0] === "customer" && parts[1]) return customer(parts[1], (qs || "").includes("run=1"));
    if (parts[0] === "check") return check();
    if (parts[0] === "watchlist") return watchlistPage();
    if (parts[0] === "cases") return cases();
    if (parts[0] === "accuracy") return accuracy();
    if (parts[0] === "help") return help();
    return home();
  } catch (e) {
    app.innerHTML = `<div class="page empty">Something went wrong: ${esc(e.message)}. Is the Amanah window still open?</div>`;
  }
}
window.addEventListener("hashchange", route);
window.addEventListener("unhandledrejection", e => toast("Could not reach Amanah — is the black window still open?"));

api("/api/stats").then(s => { $("#ai-txt").textContent = s.llm ? "AI: " + s.llm.replace("ollama · ", "") : "AI: built-in templates"; }).catch(() => {});
route();
})();
