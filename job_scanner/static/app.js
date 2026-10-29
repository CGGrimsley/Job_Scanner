/* Job Scanner web app: Jobs, Tracker, Profile and Setup, all from the local API. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
let S = null; // /api/state

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "" : "$" + Math.round(n).toLocaleString());
const STATUS_LABEL = { "": "Not tracked", saved: "Saved", applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn", dismissed: "Dismissed" };

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const out = await res.json().catch(() => ({}));
  if (res.status === 401 && out.login) location.href = "/login"; // on a home server, signed out
  if (!res.ok) throw new Error(out.error || `Error ${res.status}`);
  return out;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}
async function loadState() {
  S = await api("/api/state");
  const pill = $("#ai-pill");
  pill.textContent = S.ai.backend ? `Claude: ${S.ai.backend === "cli" ? "your subscription" : "API key"}` : "Claude: not set up";
  pill.className = "pill" + (S.ai.backend ? " ok" : "");
  if (typeof tour !== "undefined") tour.refresh();
}
const profileEmpty = () => !(S.profile.target_titles.length || S.profile.skills.length || S.profile.resumes.length || S.profile.about_me);

/* ---------- routing ---------- */
async function route() {
  const hash = decodeURIComponent(location.hash.slice(1)) || "home";
  const [name, ...rest] = hash.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === (name === "job" ? "jobs" : name)));
  try {
    if (name === "job") return await showJob(rest.join("/"));
    if (name === "tracker") return await showTracker();
    if (name === "insights") return await showInsights();
    if (name === "watch") return await showWatch();
    if (name === "profile") return showProfile();
    if (name === "setup") return await showSetup();
    if (name === "discover") return await showDiscover();
    if (name === "jobs") return await showJobs();
    return await showHome();
  } catch (e) {
    view.innerHTML = `<div class="card"><p>${esc(e.message)}</p></div>`;
  }
}
addEventListener("hashchange", route);

/* ---------- jobs ---------- */
const filters = { text: "", source: "", verdict: "", fresh: "", sort: "score", status: "", remote: "", min_pay: "", max_years: "", degree: "", clearance: "" };
const FILTER_SELECTS = ["source", "verdict", "fresh", "sort", "remote", "max_years", "degree", "clearance"];
const factTags = (j) => (j.fact_tags || []).map((t) => `<span class="tag fact">${esc(t)}</span>`).join("");
function jobRow(j) {
  const b = j.best, r = j.rules || {};
  const why = j.ai ? j.ai.summary : [...(r.reasons || []).slice(0, 2), ...(r.cautions || []).slice(0, 2)].join(" · ");
  const pay = j.pay_text || (r.pay_max ? `up to ${money(r.pay_max)}` : "");
  return `<article class="job" data-key="${esc(j.key)}">
    <div class="score ${b.verdict}">${b.score}<small>${b.by === "ai" ? "✦ " : ""}${b.verdict}</small></div>
    <div><div class="t">${esc(j.title || "(untitled)")}</div>
      <div class="m">${esc([j.company, j.location, pay].filter(Boolean).join(" · "))}</div>
      <div class="why">${esc(why)}</div>
      <div>${j.fresh ? `<span class="tag fresh" title="Posted today or yesterday: apply early">Fresh</span>` : ""}${warnTag(j.warnings)}${j.status ? `<span class="tag st">${esc(STATUS_LABEL[j.status])}</span>` : j.status_elsewhere ? `<span class="tag st">${esc(STATUS_LABEL[j.status_elsewhere.status])} on ${esc(j.status_elsewhere.where)}</span>` : ""}<span class="tag">${esc(j.source_name)}</span>${r.remote ? `<span class="tag">${esc(r.remote)}</span>` : ""}${factTags(j)}${(j.also_on || []).map((o) => `<span class="tag">${esc(o.source)}</span>`).join("")}${j.description ? "" : `<span class="tag">card only</span>`}${j.easy_apply ? `<span class="tag">Easy Apply</span>` : ""}</div>
    </div>
    <div class="side m">${esc((j.last_seen || "").slice(0, 10))}</div>
  </article>`;
}
const WARN_LABEL = { scam: "Possible scam", ghost: "May not be a live opening", caution: "Worth checking", info: "Good to know" };
function warnTag(ws) {
  const top = (ws || []).find((w) => w.level === "scam" || w.level === "ghost");
  return top ? `<span class="tag warn-${top.level}" title="${esc(top.text)}">⚠ ${WARN_LABEL[top.level]}</span>` : "";
}
function warningsHtml(ws) {
  if (!ws || !ws.length) return "";
  return `<div class="card warnings"><h2>Warning signs</h2><p class="note">Found in the posting itself. They're reasons to look closer, not a verdict.</p>
    <ul class="clean">${ws.map((w) => `<li class="warn-${w.level}"><b>${WARN_LABEL[w.level]}:</b> ${esc(w.text)}</li>`).join("")}</ul></div>`;
}
function bindRows(root) {
  root.querySelectorAll(".job").forEach((el) => el.addEventListener("click", () => (location.hash = "job/" + encodeURIComponent(el.dataset.key))));
}
const SITE_CHECK = { posting: "postings", cards: "search results" };
function healthWarning() {
  const bad = [];
  for (const [src, checks] of Object.entries(S.site_health || {})) {
    for (const [what, e] of Object.entries(checks)) if (!e.ok) bad.push(`${esc(S.sources[src] || src)} ${SITE_CHECK[what] || what} (since ${esc((e.at || "").slice(0, 10))})`);
  }
  return bad.length ? `<div class="card warnings"><b>Job Scanner can't read ${bad.join(", ")}.</b> The site has probably changed its pages.
    Open one of those pages, click the extension, then <b>Copy diagnostics</b>, and paste it into an issue or to Claude so the reader can be fixed.</div>` : "";
}
function healthList() {
  const rows = Object.entries(S.site_health || {}).flatMap(([src, checks]) => Object.entries(checks).map(([what, e]) =>
    `<li><b>${esc(S.sources[src] || src)} ${esc(SITE_CHECK[what] || what)}</b>: ${e.ok ? "read fine" : `<span class="warn-text">not readable</span> on ${esc(e.path || "?")}`} <span class="note">(${esc((e.at || "").slice(0, 16).replace("T", " "))})</span></li>`));
  return rows.length ? `<ul class="clean">${rows.join("")}</ul>` : `<p class="note">Nothing reported yet. Browse a job site with the extension on.</p>`;
}
async function showJobs() {
  const sources = Object.entries(S.sources).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  view.innerHTML = `
    <h1>Jobs</h1>
    <p class="lede">Every posting the extension has read, best fit first. ✦ marks Claude's assessment of the full posting against your résumé. The rest are quick matches to your preferences, which don't judge your chances.</p>
    ${healthWarning()}
    ${profileEmpty() ? `<div class="card"><b>Start with your Profile.</b> Add the roles you want, your skills and your résumé so the scores mean something. <a href="#profile">Fill it in</a></div>` : ""}
    <div class="toolbar">
      <input type="search" id="q" placeholder="Search title, company, location" value="${esc(filters.text)}">
      <select id="source"><option value="">All sites</option>${sources}</select>
      <select id="verdict"><option value="">Any verdict</option><option>Apply</option><option>Consider</option><option>Skip</option></select>
      <select id="fresh"><option value="">Posted any time</option><option value="1">Posted in the last day</option></select>
      <select id="sort"><option value="score">Best fit</option><option value="newest">Newest</option><option value="pay">Highest pay</option><option value="years">Fewest years asked</option></select>
      <a class="btn small" href="/api/jobs.csv">Export CSV</a>
    </div>
    <div class="toolbar">
      <select id="remote" title="Work arrangement"><option value="">Any arrangement</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select>
      <input type="number" id="min_pay" min="0" step="5000" placeholder="Min pay listed, e.g. 70000" value="${esc(filters.min_pay)}" title="Only jobs whose listed pay reaches this (yearly; hourly counts at 2,080 hours). Jobs with no pay listed are hidden.">
      <select id="max_years" title="Years of experience the posting asks for"><option value="">Any experience</option><option value="0">No years asked</option><option value="1">Up to 1 year</option><option value="2">Up to 2 years</option><option value="3">Up to 3 years</option><option value="5">Up to 5 years</option><option value="8">Up to 8 years</option></select>
      <select id="degree" title="Degree the posting requires"><option value="">Any degree</option><option value="high_school">No degree required</option><option value="associate">Associate's at most</option><option value="bachelor">Bachelor's at most</option><option value="master">Master's at most</option></select>
      <select id="clearance" title="Security clearance"><option value="">Any clearance</option><option value="none">No clearance</option><option value="obtainable">None, or can get one after hire</option></select>
    </div>
    <p class="note">Filters use what each posting says. A posting that doesn't mention years, a degree or a clearance isn't ruled out by those filters. "No degree required" includes postings that accept experience instead.</p>
    <div id="list" class="jobs"></div>`;
  for (const k of FILTER_SELECTS) $("#" + k).value = filters[k];
  const load = async () => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== ""));
    const out = await api("/api/jobs?" + q);
    const list = $("#list");
    const filtered = FILTER_SELECTS.concat(["text", "min_pay"]).some((k) => k !== "sort" && filters[k] !== "");
    list.innerHTML = out.jobs.length ? out.jobs.map(jobRow).join("") : filtered ? `<div class="empty card"><p><b>No jobs match these filters.</b></p></div>` : `<div class="empty card">
      <p><b>No jobs yet.</b></p><p>Install the Chrome extension (see <a href="#setup">Setup</a>), then browse LinkedIn, Indeed or NCWorks as usual. Jobs appear here as you scroll.</p></div>`;
    bindRows(list);
  };
  let t;
  $("#q").addEventListener("input", (e) => { filters.text = e.target.value; clearTimeout(t); t = setTimeout(load, 250); });
  $("#min_pay").addEventListener("input", (e) => { filters.min_pay = e.target.value; clearTimeout(t); t = setTimeout(load, 400); });
  for (const k of FILTER_SELECTS) $("#" + k).addEventListener("change", (e) => { filters[k] = e.target.value; load(); });
  await load();
}

/* ---------- one job ---------- */
function companyHtml(name, c) {
  const head = `<h2>About ${esc(name)}</h2>`;
  const btn = `<button class="btn small" id="company-read">${c ? "Read again" : "What does Claude know about them?"}</button>`;
  if (!c) return head + `<p class="note">Claude reads each employer once (a quick, cheap call) when it first reads one of their postings, and reuses it for the rest.</p>` + btn;
  const when = `<p class="note">From Claude's general knowledge as of ${esc((c.at || "").slice(0, 10))}. It can't browse, so it may be out of date: check anything that matters.</p>`;
  const check = c.check && c.check.length ? `<h3>Look up before you apply</h3>${list(c.check)}` : "";
  if (!c.known) return head + `<p>Claude doesn't recognise this employer well enough to say anything reliable, so it hasn't guessed.</p>` + check + when + btn;
  return head + `<p>${esc(c.summary)}</p><div>${c.industry ? `<span class="tag">${esc(c.industry)}</span>` : ""}${c.size ? `<span class="tag">${esc(c.size)}</span>` : ""}</div>`
    + (c.notes && c.notes.length ? `<h3>Worth knowing</h3>${list(c.notes)}` : "") + check + when + btn;
}
function bindCompany(key, name) {
  const b = $("#company-read");
  if (!b) return;
  b.addEventListener("click", async () => {
    b.disabled = true;
    b.innerHTML = `<span class="spinner"></span>Asking Claude…`;
    try {
      const out = await api(`/api/jobs/${encodeURIComponent(key)}/company`, {});
      $("#company-card").innerHTML = companyHtml(name, out.company);
    } catch (err) { toast(err.message); }
    bindCompany(key, name);
  });
}
const list = (items, fn = esc) => items && items.length ? `<ul class="clean">${items.map((x) => `<li>${fn(x)}</li>`).join("")}</ul>` : `<p class="note">None.</p>`;
async function showJob(key) {
  const { job: j, ai_current, todo, pay, company } = await api("/api/jobs/" + encodeURIComponent(key));
  const b = j.best, r = j.rules || {}, ai = j.ai;
  const statusOpts = S.statuses.map((s) => `<option value="${s}" ${s === (j.status || "") ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("");
  view.innerHTML = `
    <p><a href="#jobs">← All jobs</a></p>
    <div class="card detail-head">
      <div class="score ${b.verdict}">${b.score}<small>${b.by === "ai" ? "✦ " : ""}${b.verdict}</small></div>
      <div style="flex:1">
        <h1>${esc(j.title)}</h1>
        <div class="m">${esc([j.company, j.location, j.pay_text || (r.pay_max ? "up to " + money(r.pay_max) : ""), j.job_type].filter(Boolean).join(" · "))}</div>
        <div>${factTags(j)}${r.remote ? `<span class="tag">${esc(r.remote)}</span>` : ""}${(j.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}<span class="tag">${esc(j.source_name)}</span>${j.posted_text ? `<span class="tag">${esc(j.posted_text)}</span>` : ""}${j.applicants ? `<span class="tag">${j.applicants}+ applicants</span>` : ""}</div>
        <div class="actions">${(() => {
          // one main action for where this job is: read it, apply, or get ready for the interview
          const stage = ["interviewing", "offer"].includes(j.status) ? "prep" : ["applied", "rejected", "withdrawn"].includes(j.status) ? "applied" : ai ? "apply" : "read";
          const cls = (k) => "btn" + (k === stage ? " primary" : "");
          return `${stage === "prep" ? `<a class="btn primary" href="#" id="to-prep">Prepare for the interview</a>` : ""}
            <button class="${cls("read")}" id="analyze">${ai ? "Ask Claude again" : "Ask Claude about this job"}</button>
            <button class="${cls("apply")}" id="easy-apply" title="Claude writes the tailored résumé, cover letter and answers to the likely questions in one go, and saves the job to your tracker">${j.packet ? "Easy apply again" : "Easy apply"}</button>
            ${j.url ? `<a class="${cls("applied")}" href="${esc(j.url)}" target="_blank" rel="noopener">Open posting</a>` : ""}
            <details class="more"><summary class="btn">More</summary><div class="more-menu"><a href="#" id="to-tailor">Tailored résumé</a><a href="#" id="to-letter">Cover letter</a>${stage === "prep" ? "" : `<a href="#" id="to-prep">Interview prep</a>`}</div></details>`;
        })()}</div>
        ${(j.also_on || []).length ? `<p class="note">Also posted on ${j.also_on.map((o) => `<a href="#job/${encodeURIComponent(o.key)}">${esc(o.source)}</a>${o.status ? ` (${esc(STATUS_LABEL[o.status])})` : ""}`).join(", ")}. They're shown as one job.</p>` : ""}
        ${j.status_elsewhere ? `<p class="note"><b>You've marked this job ${esc(STATUS_LABEL[j.status_elsewhere.status])} on ${esc(j.status_elsewhere.where)}.</b></p>` : ""}
        <p class="note" id="ai-note">${ai && !ai_current ? "Your profile or this posting changed since Claude read it. Ask again for a fresh take." : ""}${!j.description ? " Only the search card was captured: open the posting with the extension on for Claude to read the full description." : ""}</p>
      </div>
    </div>
    ${warningsHtml(j.warnings)}
    ${j.packet || j.answers ? packetHtml(key, j) : ""}
    <div class="grid2">
      <div>
        <div class="card" id="ai-card">${ai ? aiHtml(ai) : `<h2>Claude's take</h2><p class="note">${S.ai.backend ? "Not asked yet. Click Ask Claude to get a fit score, your strengths and gaps for this role, red flags and résumé tips." : "Set up Claude on the Setup page to get a full analysis on your Claude subscription."}</p>`}</div>
        ${j.company ? `<div class="card" id="company-card">${companyHtml(j.company, company)}</div>` : ""}
        <div class="card"><h2>Quick match: ${r.score} (${r.verdict})</h2><p class="note">How well the posting matches your stated preferences. It doesn't judge your chances; Claude's take does.</p><h3>Good</h3>${list(r.reasons)}<h3>Watch out</h3>${list(r.cautions)}${payHtml(pay)}</div>
      </div>
      <div>
        <div class="card">
          <h2>Tracking</h2>
          ${j.status ? todoHtml(todo.map((n) => ({ ...n, key })), false) : ""}
          <label class="f">Status <select id="status">${statusOpts}</select></label>
          <div class="grid2"><label class="f">Applied on <input type="date" id="applied_at" value="${esc(j.applied_at || "")}"></label>
          <label class="f">Follow up on <input type="date" id="follow_up" value="${esc(j.follow_up || "")}"></label></div>
          <div class="grid2"><label class="f">Interview on <input type="date" id="interview_at" value="${esc(j.interview_at || "")}"></label>
          <label class="f">Contact <small>Recruiter or hiring manager</small><input id="contact" value="${esc(j.contact || "")}" placeholder="Name, email or LinkedIn"></label></div>
          <label class="f">Notes <textarea id="notes" placeholder="Recruiter name, referral, what you sent…">${esc(j.notes || "")}</textarea></label>
          <div class="actions"><button class="btn primary" id="save">Save</button><button class="btn danger" id="del">Delete job</button></div>
        </div>
        <div class="card" id="interview">${interviewHtml(key, j)}</div>
        <div class="card">
          <h2 id="tailor-card">Tailored résumé</h2>
          <p class="note">A version of your résumé aimed at this job: reordered and reworded in the posting's terms, using only what your résumés already say.</p>
          <label class="f">Start from <select id="tailor-resume"><option value="">The best match (Claude picks)</option>${S.profile.resumes.map((r) => `<option>${esc(r.name)}</option>`).join("")}</select></label>
          <div class="actions"><button class="btn primary" id="tailor">${j.tailored ? "Build it again" : "Build a tailored résumé"}</button>
            ${j.tailored ? exportButtons(key, "resume") : ""}</div>
          ${j.tailored ? tailoredHtml(j.tailored) : ""}
        </div>
        <div class="card">
          <h2 id="letter-card">Cover letter</h2>
          <div class="grid2">
            <label class="f">Based on <select id="letter-resume"><option value="">The best match (Claude picks)</option>${S.profile.resumes.map((r) => `<option ${j.cover_letter && j.cover_letter.resume === r.name ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label>
            <label class="f">Tone <select id="letter-tone"><option value="standard">Professional</option><option value="warm">Warm</option><option value="concise">Short and direct</option></select></label>
          </div>
          <label class="f">Anything to mention? <small>Optional: a referral, why this company, what to emphasise</small><textarea id="letter-notes" style="min-height:70px"></textarea></label>
          <div class="actions"><button class="btn primary" id="letter">${j.cover_letter ? "Write another" : "Write a cover letter"}</button>${j.cover_letter ? `<button class="btn" id="copy-letter">Copy</button>${exportButtons(key, "letter")}` : ""}</div>
          <p class="note">Written only from what your résumés and About Me show. Read it over before you send it.</p>
          ${j.cover_letter ? `<div class="letter card" style="margin-top:12px">${esc(j.cover_letter.text)}</div>` : ""}
        </div>
      </div>
    </div>
    ${j.description ? `<div class="card"><h2>The posting</h2><div class="desc">${esc(j.description)}</div></div>` : ""}`;

  $("#easy-apply").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>Claude is writing your résumé, letter and answers (a minute or two)…`;
    try {
      const out = await api(`/api/jobs/${encodeURIComponent(key)}/easy-apply`, {});
      const failed = Object.keys(out.errors || {});
      if (failed.length) toast(`Done, except: ${failed.join(", ")} (${Object.values(out.errors)[0]})`);
      await showJob(key);
      $("#packet").scrollIntoView({ behavior: "smooth" });
    } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Easy apply"; }
  });
  bindPacket(view, key, j);
  bindCompany(key, j.company);
  $("#analyze").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>Claude is reading the posting…`;
    try { await api(`/api/jobs/${encodeURIComponent(key)}/analyze`, { force: true }); await showJob(key); }
    catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Ask Claude about this job"; }
  });
  $("#save").addEventListener("click", async () => {
    try {
      await api(`/api/jobs/${encodeURIComponent(key)}/update`, { status: $("#status").value, applied_at: $("#applied_at").value, follow_up: $("#follow_up").value, interview_at: $("#interview_at").value, contact: $("#contact").value, notes: $("#notes").value });
      toast("Saved.");
      await showJob(key);
    } catch (err) { toast(err.message); }
  });
  $("#del").addEventListener("click", async () => {
    if (!confirm("Delete this job from Job Scanner?")) return;
    await api(`/api/jobs/${encodeURIComponent(key)}/delete`, {});
    location.hash = "jobs";
  });
  $("#letter").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>Writing…`;
    try { await api(`/api/jobs/${encodeURIComponent(key)}/cover-letter`, { notes: $("#letter-notes").value, resume: $("#letter-resume").value, tone: $("#letter-tone").value }); await showJob(key); }
    catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Write a cover letter"; }
  });
  const copy = $("#copy-letter");
  if (copy) copy.addEventListener("click", async () => { await navigator.clipboard.writeText(j.cover_letter.text); toast("Copied."); });
  $("#to-tailor").addEventListener("click", (e) => { e.preventDefault(); $("#tailor-card").scrollIntoView({ behavior: "smooth" }); });
  $("#to-prep").addEventListener("click", (e) => { e.preventDefault(); $("#interview-card").scrollIntoView({ behavior: "smooth" }); });
  bindInterview(key);
  if (j.status) bindTodo(view, todo.map((n) => ({ ...n, key })), () => showJob(key));
  $("#tailor").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>Building it…`;
    try { await api(`/api/jobs/${encodeURIComponent(key)}/tailor`, { resume: $("#tailor-resume").value }); await showJob(key); $("#tailor-card").scrollIntoView(); }
    catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Build a tailored résumé"; }
  });
  const copyResume = $("#copy-resume");
  if (copyResume) copyResume.addEventListener("click", async () => { await navigator.clipboard.writeText(j.tailored.text); toast("Copied."); });
  $("#to-letter").addEventListener("click", (e) => { e.preventDefault(); $("#letter-card").scrollIntoView({ behavior: "smooth" }); $("#letter-notes").focus({ preventScroll: true }); });
}
function payHtml(p) {
  if (!p || !p.n) return "";
  if (!p.enough) return `<h3>Pay compared</h3><p class="note">Only ${p.n} similar posting${p.n === 1 ? "" : "s"} with pay so far, too few to compare.</p>`;
  return `<h3>Pay compared</h3><p>Pays more than ${p.percentile}% of ${p.n} similar postings you've seen (typical ${money(p.low)}–${money(p.high)}, median ${money(p.median)}).</p>`;
}

/* ---------- insights ---------- */
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
function weekHtml(w) {
  const job = (j) => `<a href="#job/${encodeURIComponent(j.key)}">${esc(j.title || "?")}</a>${j.company ? ` <span class="note">at ${esc(j.company)}</span>` : ""}`;
  const section = (title, items, fn) => items && items.length ? `<h3>${title}</h3><ul class="clean">${items.map((x) => `<li>${fn(x)}</li>`).join("")}</ul>` : "";
  const MOVED = { interviewing: "Interview", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn" };
  const u = (w.usage || {}).week;
  return `<div class="card"><h2>This week</h2>
    <p>${plural(w.new_jobs || 0, "new job")} seen · ${plural(w.new_matches, "strong match", "strong matches")} you haven't acted on · ${plural(w.applied, "application")} sent${w.read_by_claude ? ` · ${w.read_by_claude} read by Claude` : ""}</p>
    ${section("Due now", w.due, (n) => `<b>${esc(n.title)}</b>: <a href="#job/${encodeURIComponent(n.key)}">${esc(n.title_job || "?")}</a>${n.company ? ` <span class="note">at ${esc(n.company)}</span>` : ""}`)}
    ${section("Moved forward or closed", w.moved, (j) => `<span class="tag">${esc(MOVED[j.status] || j.status)}</span> ${job(j)} <span class="note">${esc(j.at)}</span>`)}
    ${section("Best new matches you haven't acted on", w.best_unapplied, (j) => `<span class="score-chip ${j.verdict}">${j.score}</span> ${job(j)}`)}
    ${section("Applications sent", w.sent, job)}
    ${u ? `<p class="note">Claude this week: ${plural(u.calls, "call")}, ${(u.tokens || 0).toLocaleString()} tokens.</p>` : ""}
  </div>`;
}
async function showInsights() {
  const d = await api("/api/insights");
  const a = d.accuracy, sk = d.skills, pay = d.pay;
  const rate = (r) => r.decided ? `${r.rate}%${r.enough ? "" : " <small>(few)</small>"}` : "–";
  const band = (q) => q && q.n ? `${money(q.low)}–${money(q.high)} <small>median ${money(q.median)}, ${q.n} posting${q.n === 1 ? "" : "s"}${q.n < pay.min_sample ? ", too few to rely on" : ""}</small>` : `<span class="note">none listed yet</span>`;
  view.innerHTML = `<h1>Insights</h1><p class="lede">What all your jobs say together, counted from your own Job Scanner. Small numbers are labelled as small.</p>
    ${weekHtml(d.week)}
    <div class="card" id="resume-check"><h2>Résumé check</h2><p class="note"><span class="spinner"></span>Checking…</p></div>
    <div class="card"><h2>Are the ratings right?</h2>
      <p>${esc(a.note)}</p>
      <table class="tbl"><thead><tr><th>Rated when you applied</th><th>Applied</th><th>Interviews</th><th>Rejected</th><th>No reply</th><th>Waiting</th><th>Interview rate</th></tr></thead>
      <tbody>${a.rows.map((r) => `<tr><td><span class="score-chip ${r.verdict}">${r.verdict}</span></td><td>${r.applied}</td><td>${r.interview}</td><td>${r.rejected}</td><td>${r.no_reply}</td><td>${r.waiting}</td><td>${rate(r)}</td></tr>`).join("")}</tbody></table>
      <p class="note">Mark jobs Applied, Interviewing and Rejected on their pages (or the panel) and this fills in. A job is counted under the rating it had on the day you applied.</p></div>
    <div class="card"><h2>Skills your jobs keep asking for</h2>
      ${sk.jobs ? `<p class="note">From Claude's reads of the ${sk.jobs} job${sk.jobs === 1 ? "" : "s"} you're tracking or it rated Apply or Consider.</p>` : `<p class="note">Have Claude read a few jobs you'd consider and this fills in.</p>`}
      ${sk.gaps.length ? `<h3>Gaps Claude found</h3><table class="tbl"><thead><tr><th>Requirement</th><th>Jobs</th><th>How serious</th></tr></thead><tbody>${sk.gaps.map((g) => `<tr><td>${esc(g.requirement)}</td><td>${g.jobs}</td><td>${Object.entries(g.severity).map(([k, v]) => `<span class="sev ${esc(k)}">${esc(k)}${v > 1 ? " ×" + v : ""}</span>`).join(" ")}</td></tr>`).join("")}</tbody></table>` : ""}
      ${sk.missing_keywords.length ? `<h3>Terms in those postings that none of your résumés use</h3><div>${sk.missing_keywords.map((m) => `<span class="tag" title="${m.on_skills_list ? "On your skills list, but no résumé shows it" : ""}">${esc(m.term)} · ${m.jobs}${m.on_skills_list ? " ✱" : ""}</span>`).join("")}</div><p class="note">✱ on your skills list but no résumé shows it. If you've really done it, add the evidence to a résumé.</p>` : ""}
      <div class="actions"><button class="btn primary" id="plan" ${S.ai.backend && (sk.gaps.length || sk.missing_keywords.length) ? "" : "disabled"}>${d.plan ? "Make a new plan" : "Ask Claude for a realistic plan"}</button></div>
      <div id="plan-out">${d.plan ? planHtml(d.plan) : ""}</div></div>
    <div class="card"><h2>What your target jobs pay</h2>
      <p class="note">From the ${pay.listed} of ${pay.total} postings you've seen that list pay, as yearly figures (hourly × 2,080). The range is the middle half of postings.</p>
      ${pay.titles.length ? `<table class="tbl"><thead><tr><th>Title</th>${pay.titles[0].near ? "<th>In your locations or remote</th>" : ""}<th>Everywhere you've looked</th></tr></thead>
        <tbody>${pay.titles.map((t) => `<tr><td>${esc(t.title)}</td>${t.near ? `<td>${band(t.near)}</td>` : ""}<td>${band(t.everywhere)}</td></tr>`).join("")}</tbody></table>` : `<p class="note">Add the job titles you want on your Profile.</p>`}</div>`;
  $("#plan").addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.innerHTML = `<span class="spinner"></span>Claude is reading your gaps…`;
    try { const { plan } = await api("/api/insights/plan", {}); $("#plan-out").innerHTML = planHtml(plan); e.target.textContent = "Make a new plan"; }
    catch (err) { toast(err.message); e.target.textContent = "Ask Claude for a realistic plan"; }
    e.target.disabled = false;
  });
  resumeCheckCard();
}
function planHtml(p) {
  const EFFORT = { quick: "Quick", weeks: "Weeks", months: "Months", "needs experience": "Needs on-the-job experience" };
  return `<h3>Claude's plan</h3><p>${esc(p.summary)}</p><ol class="answers">${(p.themes || []).map((t) => `<li><b>${esc(t.skill)}</b> <span class="tag">${esc(EFFORT[t.effort] || t.effort)}</span> <span class="note">in ${t.jobs} job${t.jobs === 1 ? "" : "s"}</span>
    ${t.already ? `<div class="note">Already close: ${esc(t.already)}</div>` : ""}<div>${esc(t.next_step)}</div></li>`).join("")}</ol>
    <p class="note">Made ${esc((p.at || "").slice(0, 10))} from ${p.jobs} jobs.</p>`;
}

/* ---------- the application packet (Easy apply) ---------- */
function packetHtml(key, j) {
  const items = (j.answers && j.answers.items) || [];
  const doc = (name, d, what) => d ? `<div class="pk-doc"><b>${name}</b>${exportButtons(key, what)}</div>` : `<div class="pk-doc"><b>${name}</b> <span class="note">not written</span></div>`;
  return `<div class="card" id="packet"><h2>Application packet</h2>
    <p class="note">${j.packet ? `Put together ${esc((j.packet.at || "").slice(0, 10))}${j.packet.resume ? ` from "${esc(j.packet.resume)}"` : ""}. ` : ""}Everything here comes only from your résumés, About Me and application details. Read it over before you send anything.</p>
    <div class="pk-docs">${doc("Tailored résumé", j.tailored, "resume")}${doc("Cover letter", j.cover_letter, "letter")}</div>
    <h3>Answers to the questions they're likely to ask</h3>
    ${items.length ? `<ol class="answers">${items.map((a, i) => `<li><b>${esc(a.question)}</b>
      ${a.answer ? `<div class="answer">${esc(a.answer)}</div><div class="note">From: ${esc(a.basis)} · <button class="link" type="button" data-copy="${i}">Copy</button></div>`
        : `<div class="note you">You'll need to answer this one: ${esc(a.basis || "your résumés don't show it")}</div>`}</li>`).join("")}</ol>` : `<p class="note">None yet.</p>`}
    <div class="actions"><button class="btn small" id="redo-answers">${items.length ? "Answer them again" : "Draft the answers"}</button></div>
    <h3>Filling in the form</h3>
    <p class="note">Open the application, click the Job Scanner icon in Chrome, then <b>Fill this application</b>. It fills your details, attaches this résumé and letter where the form asks for them, and offers to draft answers to the form's own questions. It never submits, and it leaves questions about gender, race, veterans and disability to you.</p>
    ${j.url ? `<div class="actions"><a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">Open the posting</a></div>` : ""}</div>`;
}
function bindPacket(root, key, j) {
  const items = (j.answers && j.answers.items) || [];
  root.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => { await navigator.clipboard.writeText(items[+b.dataset.copy].answer); toast("Copied."); }));
  const redo = $("#redo-answers", root);
  if (redo) redo.addEventListener("click", async () => {
    redo.disabled = true;
    redo.innerHTML = `<span class="spinner"></span>Writing…`;
    try { await api(`/api/jobs/${encodeURIComponent(key)}/answers`, {}); await showJob(key); $("#packet").scrollIntoView(); }
    catch (err) { toast(err.message); redo.disabled = false; redo.textContent = "Draft the answers"; }
  });
}
function exportButtons(key, doc) {
  const href = (fmt) => `/api/jobs/${encodeURIComponent(key)}/export?doc=${doc}&format=${fmt}`;
  return `<a class="btn" href="${href("pdf")}" download>PDF</a><a class="btn" href="${href("docx")}" download>Word</a>`;
}
function tailoredHtml(t) {
  return `${t.check && t.check.length ? `<div class="warn"><b>Double-check these lines.</b> They contain a number that isn't in any of your résumés, so confirm it's true or remove it before you send this:${list(t.check)}</div>` : ""}
    ${t.left_out && t.left_out.length ? `<h3>Not claimed (your résumés don't show it)</h3>${list(t.left_out)}` : ""}
    ${t.changes && t.changes.length ? `<h3>What changed</h3>${list(t.changes)}` : ""}
    <h3>Preview</h3><div class="letter card">${esc(t.text)}</div>
    <div class="actions"><button class="btn small" id="copy-resume">Copy text</button></div>`;
}
function aiHtml(ai) {
  const conf = { high: "High", medium: "Medium", low: "Low: the résumé or posting is too thin to judge well" }[ai.confidence] || "";
  return `<h2>Claude's take: ${ai.fit_score} (${esc(ai.verdict)})</h2><p>${esc(ai.summary)}</p>
    ${ai.interview_odds ? `<p><b>Realistic odds:</b> ${esc(ai.interview_odds)}</p>` : ""}
    <p class="note">${ai.qualification_score != null ? `Meets the requirements: ${ai.qualification_score}/100 · ` : ""}${conf ? `Confidence: ${esc(conf)}` : ""}</p>
    <h3>Where you match</h3>${list(ai.strengths, (x) => `<b>${esc(x.requirement)}</b>: ${esc(x.evidence)}`)}
    <h3>Gaps</h3>${list(ai.gaps, (x) => `<span class="sev ${esc(x.severity)}">${esc(x.severity)}</span><b>${esc(x.requirement)}</b>. ${esc(x.how_to_address)}`)}
    ${ai.preference_conflicts && ai.preference_conflicts.length ? `<h3>Conflicts with what you want</h3>${list(ai.preference_conflicts)}` : ""}
    ${ai.red_flags && ai.red_flags.length ? `<h3>Red flags</h3>${list(ai.red_flags)}` : ""}
    ${ai.best_resume ? `<h3>Résumé to send</h3><p>${esc(ai.best_resume)}</p>` : ""}
    <h3>Résumé tips</h3>${list(ai.resume_tips)}
    ${ai.tailored_bullets && ai.tailored_bullets.length ? `<h3>Bullets tailored to this job</h3>${list(ai.tailored_bullets)}` : ""}
    ${ai.keywords && ai.keywords.length ? `<h3>Keywords to include (if true)</h3><div>${ai.keywords.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div>` : ""}
    ${ai.questions_to_ask && ai.questions_to_ask.length ? `<h3>Questions to ask them</h3>${list(ai.questions_to_ask)}` : ""}
    ${ai.salary_note ? `<h3>Pay</h3><p>${esc(ai.salary_note)}</p>` : ""}
    <p class="note">Read ${esc((ai.at || "").slice(0, 10))}</p>`;
}

/* ---------- to-dos: when to apply, reach out, follow up ---------- */
const MESSAGE_LABEL = { follow_up: "Draft the follow-up", thank_you: "Draft the thank-you", networking: "Draft the message", offer_reply: "Draft a reply" };
function todoHtml(items, withJob) {
  if (!items.length) return `<p class="note">Nothing to do right now.</p>`;
  return `<ul class="todo">${items.map((n, i) => `<li class="u-${n.urgency}" data-i="${i}">
    <div><b>${esc(n.title)}</b>${withJob ? ` · <a href="#job/${encodeURIComponent(n.key)}">${esc(n.title_job || "job")}${n.company ? " at " + esc(n.company) : ""}</a>` : ""}
      <div class="note">${esc(n.why)}</div><div class="draft"></div></div>
    <div class="todo-actions">${n.message ? `<button class="btn small" data-act="draft">${MESSAGE_LABEL[n.message]}</button>` : ""}<button class="btn small" data-act="done">Done</button></div>
  </li>`).join("")}</ul>`;
}
function bindTodo(root, items, refresh) {
  root.querySelectorAll(".todo li").forEach((li) => {
    const n = items[+li.dataset.i];
    li.querySelector('[data-act="done"]').addEventListener("click", async () => {
      await api(`/api/jobs/${encodeURIComponent(n.key)}/update`, { done: n.id });
      refresh();
    });
    const draft = li.querySelector('[data-act="draft"]');
    if (draft) draft.addEventListener("click", async () => {
      draft.disabled = true;
      draft.innerHTML = `<span class="spinner"></span>Writing…`;
      try {
        const { message } = await api(`/api/jobs/${encodeURIComponent(n.key)}/message`, { kind: n.message });
        const box = li.querySelector(".draft");
        box.innerHTML = `<label class="f">Subject <input readonly></label><textarea readonly style="min-height:160px"></textarea>
          <div class="actions"><button class="btn small" type="button">Copy</button></div>`;
        box.querySelector("input").value = message.subject;
        box.querySelector("textarea").value = message.body;
        box.querySelector("button").addEventListener("click", async () => { await navigator.clipboard.writeText(`${message.subject}\n\n${message.body}`); toast("Copied."); });
        draft.textContent = "Write it again";
      } catch (err) { toast(err.message); draft.textContent = MESSAGE_LABEL[n.message]; }
      draft.disabled = false;
    });
  });
}

/* ---------- tracker ---------- */
async function showTracker() {
  const out = await api("/api/jobs?status=tracked&sort=newest");
  const cols = ["saved", "applied", "interviewing", "offer"];
  const by = (s) => out.jobs.filter((j) => j.status === s);
  const closed = out.jobs.filter((j) => ["rejected", "withdrawn"].includes(j.status));
  const { todo } = await api("/api/todo");
  const mini = (j) => `<article class="job" data-key="${esc(j.key)}"><div><div class="t">${esc(j.title)}</div><div class="m">${esc(j.company || "")}</div>
    <div class="m">${j.best.by === "ai" ? "✦ " : ""}${j.best.verdict} ${j.best.score}${j.applied_at ? " · applied " + esc(j.applied_at) : ""}${j.follow_up ? " · follow up " + esc(j.follow_up) : ""}</div></div></article>`;
  view.innerHTML = `<h1>Tracker</h1><p class="lede">Your applications, from saved to offer. Change a job's status on its page, or with the buttons in the extension's panel.</p>
    <div class="card"><h2>To do</h2><p class="note">When to apply, reach out, follow up and say thank you, worked out from the dates you record. Claude can draft each message.</p>${todoHtml(todo, true)}</div>
    <div class="board">${cols.map((c) => `<section class="col"><h2>${STATUS_LABEL[c]} <span>${by(c).length}</span></h2><div class="jobs">${by(c).map(mini).join("") || `<p class="note">None yet.</p>`}</div></section>`).join("")}</div>
    ${closed.length ? `<div class="card" style="margin-top:16px"><h2>Closed</h2><div class="jobs">${closed.map(mini).join("")}</div></div>` : ""}`;
  bindRows(view);
  bindTodo(view, todo, showTracker);
}

/* ---------- profile ---------- */
const APPLY_TEXT = [["first_name", "First name"], ["last_name", "Last name"], ["email", "Email"], ["phone", "Phone"],
  ["street", "Street address"], ["city", "City"], ["state", "State"], ["postal_code", "ZIP / postal code"], ["country", "Country", "United States"],
  ["linkedin", "LinkedIn", "linkedin.com/in/…"], ["website", "Website or portfolio"], ["github", "GitHub"],
  ["current_title", "Current job title"], ["current_company", "Current employer"], ["school", "School"], ["degree", "Degree", "B.S. Accounting"],
  ["start_date", "Earliest start", "Two weeks' notice"], ["salary_expectation", "Salary expectation", "$60,000–$70,000"], ["how_heard", "How you heard about jobs", "LinkedIn"]];
const APPLY_YES_NO = [["work_authorized", "Authorized to work in the US?"], ["sponsorship", "Will you need visa sponsorship?"], ["relocate", "Willing to relocate?"], ["over_18", "18 or older?"]];
function showProfile() {
  const p = S.profile, c = S.choices;
  const checks = (name, opts, chosen) => `<div class="checks">${opts.map((o) => `<label><input type="checkbox" name="${name}" value="${o}" ${chosen.includes(o) ? "checked" : ""}> ${o}</label>`).join("")}</div>`;
  view.innerHTML = `<h1>Your profile</h1>
    <p class="lede">Everything here stays on this computer. The quick scores use your preferences; Claude reads all of it, including your résumé and About Me, when it judges a posting.</p>
    <form id="pf">
          <div class="card"><h2>1. Your résumés</h2>
            <p class="note">Start here. Upload or paste your résumé and Claude suggests job titles and skills from it; you can change them and add your own below. Add every version you use (say, one for analyst roles and one for operations). Claude reads them all as evidence of what you've done, and tells you which one to send for each job.</p>
            <div id="resumes"></div>
            <div class="actions" style="margin:0 0 10px"><button class="btn small" type="button" id="add-resume">+ Paste another</button>
              <label class="btn small" tabindex="0">Upload PDF, Word or text<input type="file" id="resume-file" accept=".pdf,.docx,.txt,.md" multiple hidden></label>
              <button class="btn small" type="button" id="suggest" ${S.ai.backend ? "" : "disabled"}>Suggest job titles and skills from them</button></div>
            <p class="note" id="resume-note">${S.ai.backend ? "PDFs are read by Claude on your subscription." : "Word and text files are read here. PDFs need Claude set up; or paste the text."}</p>
          </div>
      <div class="grid2">
        <div class="card"><h2>2. What you're looking for</h2>
          <label class="f">Job titles you want <small>Suggested from your résumés; add your own, one per line</small><textarea name="target_titles" style="min-height:90px">${esc(p.target_titles.join("\n"))}</textarea></label>
          <label class="f">Your skills <small>Comma or line separated: tools, certifications, specialties</small><textarea name="skills" style="min-height:90px">${esc(p.skills.join(", "))}</textarea></label>
          <div class="f"><label for="place-q">Locations</label> <small class="note">Start typing a city or state and pick it. A state covers every job in it.</small>
            <div class="chips" id="places"></div>
            <div class="picker"><input id="place-q" autocomplete="off" placeholder="e.g. Raleigh or North Carolina" role="combobox" aria-expanded="false" aria-controls="place-list" aria-autocomplete="list">
              <ul id="place-list" role="listbox" hidden></ul></div></div>
          <label class="f">Work arrangement ${checks("remote", c.remote, p.remote)}</label>
          <label class="f">Job type ${checks("job_types", c.job_types, p.job_types)}</label>
          <label class="f">Level <small>Leave all unticked for any</small>${checks("seniority", c.seniority, p.seniority)}</label>
          <div class="grid2">
            <label class="f">Minimum yearly pay <small>Hourly pay is counted at 2,080 hours</small><input name="min_salary" inputmode="numeric" value="${esc(p.min_salary ?? "")}" placeholder="55000"></label>
            <label class="f">Years of experience <input name="years_experience" inputmode="decimal" value="${esc(p.years_experience ?? "")}"></label>
          </div>
          <label class="f">Skip postings that mention <small>Comma separated, e.g. commission only, door to door</small><input name="avoid_keywords" value="${esc(p.avoid_keywords.join(", "))}"></label>
          <label class="f">Dealbreakers, in your words <small>For Claude: e.g. no night shifts, under 25% travel, need visa sponsorship</small><textarea name="dealbreakers" style="min-height:70px">${esc(p.dealbreakers)}</textarea></label>
        </div>
        <div>
          <div class="card"><h2>3. About me</h2>
            <label class="f">Name <small>Used on cover letters</small><input name="name" value="${esc(p.name)}"></label>
            <label class="f">About me <small>Who you are, what you want next, what you're good at, what matters to you in a job. The more Claude knows, the better its advice.</small><textarea name="about_me" style="min-height:180px">${esc(p.about_me)}</textarea></label>
            <div class="actions" style="margin-top:0"><button class="btn small" type="button" id="about-draft" ${S.ai.backend ? "" : "disabled"} title="Claude writes a draft from your résumés for you to edit">${p.about_me ? "Rework it from my résumés" : "Draft it from my résumés"}</button></div>
            <div class="note" id="about-note">${S.ai.backend ? "" : "Set up Claude on the Setup page to draft this from your résumés."}</div>
          </div>
        </div>
      </div>
      <div class="card"><h2>4. Application details</h2>
        <p class="note">What application forms ask for again and again. The extension's <b>Fill this application</b> copies these into forms you open, for you to check before you submit. Leave anything blank you'd rather type yourself. Yes/no answers are only ever taken from here, never guessed.</p>
        <div class="grid3">${APPLY_TEXT.map(([k, label, ph]) => `<label class="f">${label}<input name="a_${k}" value="${esc((p.apply || {})[k] || "")}" placeholder="${esc(ph || "")}"></label>`).join("")}</div>
        <div class="grid3">${APPLY_YES_NO.map(([k, label]) => `<label class="f">${label}<select name="a_${k}">${["", "yes", "no"].map((v) => `<option value="${v}" ${((p.apply || {})[k] || "") === v ? "selected" : ""}>${{ "": "Leave blank", yes: "Yes", no: "No" }[v]}</option>`).join("")}</select></label>`).join("")}</div>
      </div>
      <div class="actions"><button class="btn primary" type="submit">Save profile</button></div>
    </form>`;
  const f = $("#pf");
  const collect = () => {
    const fd = new FormData(f);
    const out = {};
    for (const k of ["name", "about_me", "dealbreakers", "min_salary", "years_experience"]) out[k] = fd.get(k);
    out.resumes = resumes();
    for (const k of ["target_titles", "skills", "avoid_keywords"]) out[k] = fd.get(k);
    out.locations = chosenPlaces;
    for (const k of ["remote", "job_types", "seniority"]) out[k] = fd.getAll(k);
    out.max_age_days = S.profile.max_age_days;
    out.apply = {};
    for (const [k] of APPLY_TEXT.concat(APPLY_YES_NO)) out.apply[k] = fd.get("a_" + k) || "";
    return out;
  };
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const out = await api("/api/profile", { profile: collect() });
      S.profile = out.profile;
      toast(`Saved. ${out.counts.total} jobs rescored.`);
      tour.refresh();
    } catch (err) { toast(err.message); }
  });
  // locations: chips, added from a type-ahead list of real places (typing your own and pressing Enter works too)
  let chosenPlaces = [...p.locations];
  const chips = $("#places"), q = $("#place-q"), listEl = $("#place-list");
  let options = [], active = -1, seq = 0;
  function drawChips() {
    chips.innerHTML = chosenPlaces.map((x, i) => `<span class="chip">${esc(x)}<button type="button" data-i="${i}" aria-label="Remove ${esc(x)}">×</button></span>`).join("");
    chips.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { chosenPlaces.splice(+b.dataset.i, 1); drawChips(); }));
  }
  function drawOptions() {
    listEl.hidden = !options.length;
    q.setAttribute("aria-expanded", String(!!options.length));
    listEl.innerHTML = options.map((x, i) => `<li role="option" id="place-${i}" aria-selected="${i === active}" class="${i === active ? "on" : ""}">${esc(x)}</li>`).join("");
    listEl.querySelectorAll("li").forEach((li, i) => li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(options[i]); }));
    if (active >= 0) q.setAttribute("aria-activedescendant", `place-${active}`); else q.removeAttribute("aria-activedescendant");
  }
  function pick(place) {
    place = place.trim();
    if (place && !chosenPlaces.some((x) => x.toLowerCase() === place.toLowerCase())) chosenPlaces.push(place);
    q.value = ""; options = []; active = -1;
    drawChips(); drawOptions();
  }
  let t;
  q.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const mine = ++seq;
      const out = q.value.trim().length >= 2 ? await api("/api/places?q=" + encodeURIComponent(q.value)).catch(() => ({ places: [] })) : { places: [] };
      if (mine !== seq) return;
      options = out.places; active = options.length ? 0 : -1;
      drawOptions();
    }, 150);
  });
  q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && options.length) { e.preventDefault(); active = (active + 1) % options.length; drawOptions(); }
    else if (e.key === "ArrowUp" && options.length) { e.preventDefault(); active = (active - 1 + options.length) % options.length; drawOptions(); }
    else if (e.key === "Enter") { e.preventDefault(); if (active >= 0) pick(options[active]); else if (q.value.trim()) pick(q.value); }
    else if (e.key === "Escape") { options = []; drawOptions(); }
    else if (e.key === "Backspace" && !q.value && chosenPlaces.length) { chosenPlaces.pop(); drawChips(); }
  });
  q.addEventListener("blur", () => setTimeout(() => { options = []; drawOptions(); }, 100));
  drawChips();

  const box = $("#resumes");
  function addResume(name = "", text = "") {
    const n = box.children.length + 1;
    const el = document.createElement("div");
    el.className = "resume";
    el.innerHTML = `<div class="resume-head"><input class="r-name" placeholder="Name, e.g. Data analyst" aria-label="Résumé name">
      <button class="btn small danger" type="button">Remove</button></div>
      <textarea class="r-text" style="min-height:200px" placeholder="Paste a résumé here"></textarea>`;
    el.querySelector(".r-name").value = name || (n === 1 ? "Main résumé" : `Résumé ${n}`);
    el.querySelector(".r-text").value = text;
    el.querySelector("button").addEventListener("click", () => { el.remove(); if (!box.children.length) addResume(); });
    box.appendChild(el);
    return el;
  }
  const resumes = () => [...box.querySelectorAll(".resume")].map((el) => ({ name: el.querySelector(".r-name").value.trim(), text: el.querySelector(".r-text").value.trim() })).filter((r) => r.text);
  (p.resumes.length ? p.resumes : [{}]).forEach((r) => addResume(r.name, r.text));
  $("#add-resume").addEventListener("click", () => addResume().querySelector(".r-name").select());
  $("#resume-file").addEventListener("change", async (e) => {
    const note = $("#resume-note");
    for (const file of e.target.files) {
      note.innerHTML = `<span class="spinner"></span>Reading ${esc(file.name)}…`;
      const data = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(file); });
      try {
        const out = await api("/api/profile/resume-file", { filename: file.name, data });
        // fill the first empty slot, else add one, named after the file
        const empty = [...box.querySelectorAll(".resume")].find((el) => !el.querySelector(".r-text").value.trim());
        const el = empty || addResume();
        el.querySelector(".r-name").value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
        el.querySelector(".r-text").value = out.resume_text;
        if (!out.titles && S.ai.backend) {
          note.innerHTML = `<span class="spinner"></span>Claude is suggesting job titles…`;
          try { Object.assign(out, await api("/api/profile/suggest", { resume: out.resume_text })); } catch (_) { /* suggestions are optional */ }
        }
        applySuggestions(out);
        note.textContent = out.titles ? "Read, and suggested titles and skills added below. Check them over, then Save profile." : "Read. Check it over, then Save profile.";
        if (S.ai.backend && !f.elements.about_me.value.trim()) draftAbout(); // nothing written yet: start them off
      } catch (err) { note.textContent = `${file.name}: ${err.message}`; }
    }
    e.target.value = "";
  });
  async function draftAbout() {
    const btn = $("#about-draft"), box = f.elements.about_me, note = $("#about-note");
    if (btn.disabled) return; // already drafting
    const text = resumes().map((r) => `# ${r.name}\n${r.text}`).join("\n\n");
    if (text.length < 100) { note.textContent = "Add a résumé above first: the draft is written from it."; return; }
    btn.disabled = true;
    note.innerHTML = `<span class="spinner"></span>Claude is drafting from your résumés…`;
    try {
      const out = await api("/api/profile/about-draft", { resume: text, current: box.value });
      const before = box.value;
      box.value = out.about_me;
      note.innerHTML = `<b>Drafted from your résumés only, not saved yet.</b> Edit it so it sounds like you, then <b>Save profile</b>.`
        + ((out.check || []).length ? `<br><span class="warn-text">These figures aren't in your résumés; check them:</span>${list(out.check)}` : "")
        + (out.to_add.length ? ` Worth adding in your own words:${list(out.to_add)}` : "")
        + (before.trim() ? ` <a href="#" id="about-undo">Undo</a>` : "");
      const undo = $("#about-undo");
      if (undo) undo.addEventListener("click", (ev) => { ev.preventDefault(); box.value = before; note.textContent = "Put back what you had."; });
      btn.textContent = "Rework it from my résumés";
    } catch (err) { note.textContent = err.message; }
    btn.disabled = false;
  }
  $("#about-draft").addEventListener("click", draftAbout);
  $("#suggest").addEventListener("click", async (e) => {
    e.target.disabled = true;
    const note = $("#resume-note");
    note.innerHTML = `<span class="spinner"></span>Claude is reading your résumés…`;
    const text = resumes().map((r) => `# ${r.name}\n${r.text}`).join("\n\n");
    try { applySuggestions(await api("/api/profile/suggest", { resume: text })); note.textContent = "Added suggestions. Edit them, then Save profile."; }
    catch (err) { note.textContent = err.message; }
    e.target.disabled = false;
  });
  function applySuggestions(out) {
    const merge = (field, items, sep) => {
      if (!items || !items.length) return;
      const have = f[field].value.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
      const lower = new Set(have.map((x) => x.toLowerCase()));
      f[field].value = have.concat(items.filter((x) => !lower.has(x.toLowerCase()))).join(sep);
    };
    merge("target_titles", out.titles, "\n");
    merge("skills", out.skills, ", ");
    if (out.years_experience != null && !f.years_experience.value) f.years_experience.value = out.years_experience;
  }
}

/* ---------- watching: automatic sources ---------- */
const BOARD_NAMES = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters" };
async function showWatch() {
  const w = await api("/api/watch");
  const c = w.config, st = w.state, src = st.sources || {};
  const when = (iso) => iso ? iso.slice(0, 16).replace("T", " ") : "never";
  const runLine = (id) => {
    const r = src[id];
    if (!r) return `<span class="note">Not checked yet</span>`;
    return r.ok ? `<span class="note">Checked ${esc(when(r.at))}: ${r.found} open, ${r.kept} worth a look, ${r.added} new</span>`
      : `<span class="warn-text">${esc(r.error)}</span> <span class="note">(${esc(when(r.at))})</span>`;
  };
  const near = c.nearby;
  const nearRow = (e, i) => {
    const wb = e.watchable, watched = wb && c.boards.some((b) => b.provider === wb.provider && b.token.toLowerCase() === wb.token.toLowerCase());
    return `<tr><td><b>${esc(e.name)}</b><div class="note">${esc(e.industry)}${e.size ? " · " + esc(e.size) : ""}</div><div class="note">${esc(e.why)}</div></td>
      <td>${e.careers_url ? `<a href="${esc(e.careers_url)}" target="_blank" rel="noopener">Careers page</a>${e.link_ok === false ? ` <span class="warn-text" title="This link didn't open from here">(link didn't open)</span>` : ""}` : `<span class="note">No link known</span>`}</td>
      <td>${wb ? `${esc(BOARD_NAMES[wb.provider])} · ${wb.jobs} open${wb.guessed ? `<div class="note">Found by guessing its name: <a href="${esc(boardLink(wb))}" target="_blank" rel="noopener">check it's theirs</a></div>` : ""}`
        : `<span class="note">${esc(e.board && e.board !== "unknown" ? e.board : "Unknown board")}: open the careers page and browse; the extension reads it</span>`}</td>
      <td>${wb ? (watched ? `<span class="tag st">Watching</span>` : `<button class="btn small" data-near="${i}">Watch</button>`) : ""}</td></tr>`;
  };
  view.innerHTML = `<h1>Watching</h1>
    <p class="lede">Sources Job Scanner checks by itself every ${c.every_hours === 1 ? "hour" : c.every_hours + " hours"} while it's running. Jobs worth a look (quick score ${c.min_score}+, in your places) are added to your Jobs list like the ones you browse, and strong matches get a notification. LinkedIn and Indeed are never loaded automatically: their terms forbid it, so they come in through your alert emails below.</p>
    <div class="actions" style="margin:0 0 14px"><button class="btn primary" id="run-now" ${w.running ? "disabled" : ""}>${w.running ? "Checking…" : "Check everything now"}</button>
      <span class="note" style="align-self:center">Last checked: ${esc(when(st.last_run))}</span></div>

    ${setupCard(w, near)}

    <div class="card"><h2>Employers near you</h2>
      <p class="note">Claude lists the prominent employers around ${esc((near && near.places || []).join("; ") || w.where || "your places")} that hire for the roles you want, and where each one posts its jobs. The list comes from Claude's general knowledge, so it can be out of date. Every link and board is checked from this computer before it's shown as watchable.</p>
      <div class="actions"><button class="btn" id="find-near" ${S.ai.backend ? "" : "disabled"}>${near ? "Find again" : "Find employers near me"}</button>${near ? `<span class="note" style="align-self:center">Found ${esc(when(near.at))}</span>` : ""}</div>
      ${near && near.items.length ? `<table class="results"><thead><tr><th>Employer</th><th>Careers page</th><th>Job board</th><th></th></tr></thead><tbody>${near.items.map(nearRow).join("")}</tbody></table>` : ""}
    </div>

    <div class="card"><h2>Company job boards</h2>
      <p class="note">Employers on Greenhouse, Lever, Ashby or SmartRecruiters publish their jobs for programs to read. Paste a link to one's board (from the Apply button on any of their jobs, e.g. <code>https://jobs.lever.co/acme</code>).</p>
      <div class="token"><input id="board-url" placeholder="https://boards.greenhouse.io/acme"><button class="btn" id="add-board">Watch</button></div>
      ${c.boards.length ? `<ul class="clean">${c.boards.map((b) => `<li><b>${esc(b.name)}</b> <span class="note">${esc(BOARD_NAMES[b.provider])} · <a href="${esc(boardLink(b))}" target="_blank" rel="noopener">${esc(b.token)}</a></span> ${runLine(`board:${b.provider}:${b.token}`)} <button class="btn small" data-remove="${esc(b.provider)}|${esc(b.token)}">Stop</button></li>`).join("")}</ul>` : `<p class="note">None yet.</p>`}
    </div>

    <div class="card"><h2>Job alert emails (LinkedIn and Indeed)</h2>
      <p class="note">Set up job alerts on LinkedIn and Indeed for your searches; they email you new matches. Job Scanner reads those emails from your mailbox <b>read-only</b> (nothing is marked read, moved or deleted) and adds each job. Open one in Chrome and the extension reads the full posting. Gmail, Yahoo and iCloud need an <b>app password</b> (made in your account's security settings), not your normal password. Outlook.com and Hotmail don't allow this kind of sign-in.</p>
      <label class="f"><input type="checkbox" id="em-on" ${c.email.enabled ? "checked" : ""}> Check my alert emails</label>
      <div class="grid2"><label class="f">Mail server <input id="em-host" value="${esc(c.email.host)}" placeholder="imap.gmail.com"></label>
        <label class="f">Folder <input id="em-folder" value="${esc(c.email.folder)}" placeholder="INBOX"></label>
        <label class="f">Email address <input id="em-user" value="${esc(c.email.user)}" autocomplete="off"></label>
        <label class="f">App password <small>${c.email.password_set ? "Saved. Leave blank to keep it." : "Stored only on this computer."}</small><input id="em-pass" type="password" autocomplete="new-password"></label></div>
      <div class="actions"><button class="btn" id="em-test">Test</button><span id="em-note" class="note" style="align-self:center"></span></div>
      <p>${runLine("email")}</p>
    </div>

    <div class="grid2">
      <div class="card"><h2>USAJobs (federal jobs)</h2>
        <p class="note">Free key from <a href="https://developer.usajobs.gov/apirequest/" target="_blank" rel="noopener">developer.usajobs.gov</a>; it's tied to the email you register with.</p>
        <label class="f"><input type="checkbox" id="us-on" ${c.usajobs.enabled ? "checked" : ""}> Search USAJobs</label>
        <label class="f">Registered email <input id="us-email" value="${esc(c.usajobs.email)}"></label>
        <label class="f">API key <small>${c.usajobs.key_set ? "Saved. Leave blank to keep it." : ""}</small><input id="us-key" type="password" autocomplete="off"></label>
        <p>${runLine("usajobs")}</p></div>
      <div class="card"><h2>Adzuna (many job boards)</h2>
        <p class="note">Free key from <a href="https://developer.adzuna.com/" target="_blank" rel="noopener">developer.adzuna.com</a>. Adzuna only gives a short preview, so these come in as cards: open one and the extension reads the full posting.</p>
        <label class="f"><input type="checkbox" id="az-on" ${c.adzuna.enabled ? "checked" : ""}> Search Adzuna</label>
        <label class="f">App ID <input id="az-id" value="${esc(c.adzuna.app_id)}"></label>
        <label class="f">App key <small>${c.adzuna.app_key_set ? "Saved. Leave blank to keep it." : ""}</small><input id="az-key" type="password" autocomplete="off"></label>
        <p>${runLine("adzuna")}</p></div>
    </div>

    <div class="card"><h2>Searches and schedule</h2>
      <div class="grid2"><label class="f">Search for <small>One per line. Blank uses your target roles: ${esc(w.keywords.join(", ") || "none yet")}</small><textarea id="kw" style="min-height:80px">${esc(c.searches.keywords.join("\n"))}</textarea></label>
        <div><label class="f">Near <small>Blank uses ${esc(w.where || "your first place")}</small><input id="where" value="${esc(c.searches.where)}"></label>
          <label class="f">Within (miles) <input type="number" id="radius" min="1" max="200" value="${c.searches.radius_miles}"></label></div>
        <label class="f">Check every (hours) <input type="number" id="every" min="1" max="48" value="${c.every_hours}"></label>
        <label class="f">Keep jobs with a quick score of at least <input type="number" id="minscore-w" min="0" max="100" value="${c.min_score}"></label></div>
      <div class="actions"><button class="btn primary" id="save-watch">Save</button></div>
    </div>`;

  const busy = (b, label) => { b.disabled = true; b.innerHTML = `<span class="spinner"></span>${label}`; };
  $("#run-now").addEventListener("click", async (e) => {
    busy(e.target, "Checking…");
    await api("/api/watch/run", {});
    const poll = setInterval(async () => {
      const now = await api("/api/watch");
      if (!now.running) { clearInterval(poll); toast("Checked."); if (location.hash === "#watch") showWatch(); }
    }, 3000);
  });
  $("#auto-setup")?.addEventListener("click", async (e) => {
    busy(e.target, "Finding employers near you and checking each board (a minute or two)…");
    try {
      await api("/api/watch/setup", {});
      const poll = setInterval(async () => {
        const now = await api("/api/watch");
        if (!now.setting_up) { clearInterval(poll); if (location.hash === "#watch") showWatch(); }
      }, 3000);
    } catch (err) { toast(err.message); e.target.disabled = false; e.target.textContent = "Set it up for me"; }
  });
  $("#watch-confirmed")?.addEventListener("click", async () => {
    try { const out = await api("/api/watch/confirmed", {}); toast(out.added.length ? `Watching ${out.added.length} more employers.` : "Already watching them all."); await showWatch(); }
    catch (err) { toast(err.message); }
  });
  $("#auto-boards")?.addEventListener("change", async (e) => {
    try { await api("/api/watch", { auto_boards: e.target.checked }); toast("Saved."); } catch (err) { toast(err.message); }
  });
  $("#find-near").addEventListener("click", async (e) => {
    busy(e.target, "Claude is listing employers, then each one is checked (a minute or two)…");
    try { await api("/api/watch/nearby", {}); await showWatch(); } catch (err) { toast(err.message); e.target.disabled = false; e.target.textContent = "Find employers near me"; }
  });
  view.querySelectorAll("[data-near]").forEach((b) => b.addEventListener("click", async () => {
    const e = near.items[+b.dataset.near];
    try { await api("/api/watch/board", { provider: e.watchable.provider, token: e.watchable.token, name: e.name }); toast(`Watching ${e.name}.`); await showWatch(); }
    catch (err) { toast(err.message); }
  }));
  $("#add-board").addEventListener("click", async (e) => {
    busy(e.target, "Checking…");
    try { const out = await api("/api/watch/board", { url: $("#board-url").value }); toast(`Watching: ${out.jobs} jobs open there now.`); await showWatch(); }
    catch (err) { toast(err.message); e.target.disabled = false; e.target.textContent = "Watch"; }
  });
  view.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    const [provider, token] = b.dataset.remove.split("|");
    await api("/api/watch/board/remove", { provider, token });
    await showWatch();
  }));
  const settingsBody = () => ({
    every_hours: $("#every").value, min_score: $("#minscore-w").value,
    searches: { keywords: $("#kw").value, where: $("#where").value, radius_miles: $("#radius").value },
    email: { enabled: $("#em-on").checked, host: $("#em-host").value, folder: $("#em-folder").value, user: $("#em-user").value, password: $("#em-pass").value },
    usajobs: { enabled: $("#us-on").checked, email: $("#us-email").value, key: $("#us-key").value },
    adzuna: { enabled: $("#az-on").checked, app_id: $("#az-id").value, app_key: $("#az-key").value },
  });
  $("#save-watch").addEventListener("click", async () => {
    try { await api("/api/watch", settingsBody()); toast("Saved."); await showWatch(); } catch (err) { toast(err.message); }
  });
  $("#em-test").addEventListener("click", async (e) => {
    const note = $("#em-note");
    note.innerHTML = `<span class="spinner"></span>Opening your mailbox…`;
    try {
      const out = await api("/api/watch/test-email", { email: settingsBody().email });
      note.textContent = out.ok ? "Signed in. Save to start checking." : out.error;
    } catch (err) { note.textContent = err.message; }
  });
}
function setupCard(w, near) {
  const c = w.config, done = (w.state || {}).autosetup;
  const confirmed = (near && near.items || []).filter((e) => e.watchable && !e.watchable.guessed);
  const unwatched = confirmed.filter((e) => !c.boards.some((b) => b.provider === e.watchable.provider && b.token.toLowerCase() === e.watchable.token.toLowerCase()));
  const mailOff = !c.email.enabled;
  return `<div class="card next"><h2>Set up for you</h2>
    <p class="note">Job Scanner finds the prominent employers near your places, watches every job board it can confirm is theirs, and checks them every hour. It does this by itself when your places change (or once a day until it works). Boards it could only guess at are left for you to check.</p>
    ${w.setting_up ? `<p><span class="spinner"></span>Setting up now: finding employers and checking each board…</p>` : done ? `<p>Last set up ${esc((done.at || "").slice(0, 10))}: ${done.employers} employers found, ${done.watched.length} boards watched${done.watched.length ? ` (${esc(done.watched.slice(0, 6).join(", "))}${done.watched.length > 6 ? "…" : ""})` : ""}.</p>` : ""}
    <div class="actions"><button class="btn primary" id="auto-setup" ${w.setting_up || !S.ai.backend ? "disabled" : ""}>${done ? "Set it up again" : "Set it up for me"}</button>
      ${unwatched.length ? `<button class="btn" id="watch-confirmed">Watch the ${unwatched.length} confirmed board${unwatched.length > 1 ? "s" : ""} below</button>` : ""}</div>
    <label class="f"><input type="checkbox" id="auto-boards" ${c.auto_boards ? "checked" : ""}> Keep this set up by itself when my places change</label>
    ${mailOff ? `<p class="note"><b>One thing only you can do:</b> LinkedIn and Indeed jobs come in through their alert emails. Set up alerts there, then fill in <b>Job alert emails</b> below with an app password.</p>` : ""}
  </div>`;
}
function boardLink(b) {
  return { greenhouse: `https://job-boards.greenhouse.io/${b.token}`, lever: `https://jobs.lever.co/${b.token}`,
    ashby: `https://jobs.ashbyhq.com/${b.token}`, smartrecruiters: `https://careers.smartrecruiters.com/${b.token}` }[b.provider];
}

/* ---------- your phone (ntfy) ---------- */
function phoneCard(s) {
  const hours = [[-1, "No morning brief"], ...Array.from({ length: 24 }, (_, h) => [h, `${String(h).padStart(2, "0")}:00`])];
  return `<div class="card"><h2>Your phone</h2>
    <p class="note">Job Scanner sends strong matches it finds by itself to your phone, once Claude has read them, and a short brief each morning: fresh jobs, new matches, follow-ups due and interviews coming up. It uses <a href="https://ntfy.sh" target="_blank" rel="noopener">ntfy</a>, which is free with no account. Install the ntfy app, subscribe to a topic name only you know, and paste it here. Anyone who knows the name can read the alerts, so keep it long and random.</p>
    <div class="grid2">
      <label class="f">ntfy topic <span class="token"><input id="ph-topic" value="${esc(s.phone_topic)}" placeholder="e.g. jobs-k3v9q2x7m1" autocomplete="off"><button class="btn small" id="ph-make" type="button">Make one</button></span></label>
      <label class="f">Send a job when Claude rates it Apply at least <small>Jobs posted in the last day get 10 points of slack. Without Claude's read, only a quick score of 80+ is sent.</small><input type="number" id="ph-min" min="0" max="100" value="${s.phone_min}"></label>
      <label class="f">Morning brief at <small>This server's local time</small><select id="ph-brief">${hours.map(([v, l]) => `<option value="${v}" ${+s.brief_hour === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f">This app's address <small>For the "In Job Scanner" button on alerts, e.g. https://jobs.example.com</small><input id="ph-app" value="${esc(s.app_url)}" placeholder="${esc(location.origin)}"></label>
    </div>
    <details><summary>Your own ntfy server</summary><label class="f">ntfy server <input id="ph-server" value="${esc(s.phone_server)}" placeholder="https://ntfy.sh"></label></details>
    <div class="actions"><button class="btn primary" id="ph-save">Save</button><button class="btn" id="ph-test">Send a test</button><button class="btn" id="ph-brief-now">Send this morning's brief now</button><span class="note" id="ph-out" style="align-self:center"></span></div>
  </div>`;
}
function bindPhone() {
  const out = $("#ph-out");
  $("#ph-make").addEventListener("click", () => {
    const a = new Uint8Array(9); crypto.getRandomValues(a);
    $("#ph-topic").value = "jobs-" + Array.from(a, (b) => "abcdefghjkmnpqrstuvwxyz23456789"[b % 31]).join("");
  });
  const save = async () => {
    const outS = await api("/api/settings", { phone_topic: $("#ph-topic").value, phone_min: $("#ph-min").value, brief_hour: $("#ph-brief").value,
      app_url: $("#ph-app").value, phone_server: $("#ph-server").value });
    S.settings = outS.settings;
  };
  $("#ph-save").addEventListener("click", async () => { try { await save(); toast("Saved."); } catch (err) { toast(err.message); } });
  $("#ph-test").addEventListener("click", async () => {
    try { await save(); const r = await api("/api/alerts/test", {}); out.textContent = r.ok ? "Sent. Check your phone." : r.error; }
    catch (err) { out.textContent = err.message; }
  });
  $("#ph-brief-now").addEventListener("click", async () => {
    try { await save(); const r = await api("/api/alerts/brief", {}); out.textContent = r.sent ? "Sent." : r.ok ? "Nothing to report right now, so nothing was sent." : r.error; }
    catch (err) { out.textContent = err.message; }
  });
}

/* ---------- setup ---------- */
const onThisComputer = () => ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
const MODELS = [["haiku", "Haiku (fast, light on your plan)"], ["sonnet", "Sonnet (balanced)"], ["opus", "Opus (most thorough)"]];
const modelOpts = (v, dflt) => `<option value="">${esc(dflt)}</option>` + MODELS.map(([k, label]) => `<option value="${k}" ${v === k ? "selected" : ""}>${label}</option>`).join("");
async function showSetup() {
  const [{ token }, usage] = await Promise.all([api("/api/token"), api("/api/ai/usage")]);
  const a = S.ai, s = S.settings;
  view.innerHTML = `<h1>Setup</h1>
    <div class="grid2">
      <div class="card"><h2>1. Claude, on your subscription</h2>
        <p>Status: <b>${esc(a.label)}</b> <button class="btn small" id="test-ai" ${a.backend ? "" : "disabled"}>Test it</button></p>
        <p id="test-out" class="note"></p>
        ${a.limited ? `<p class="warn-text">${esc(a.limited)} Automatic reads are paused until then; Ask Claude still tries.</p>` : ""}
        <details ${a.backend ? "" : "open"}><summary>How to sign Claude Code in</summary>
        <ol class="steps">
          <li>Open <b>PowerShell</b> (Windows: press the Windows key, type PowerShell, press Enter) or <b>Terminal</b> (Mac).</li>
          <li>Type <code>claude</code> and press Enter. If it isn't found, install it first: <code>npm install -g @anthropic-ai/claude-code</code> (it needs Node.js 22 or newer; check with <code>node -v</code>, and update with <code>winget install OpenJS.NodeJS.LTS</code> or from nodejs.org).</li>
          <li>If Windows says <i>running scripts is disabled</i>, run <code>Set-ExecutionPolicy -Scope CurrentUser RemoteSigned</code>, answer Y, and try <code>claude</code> again.</li>
          <li>Choose <b>Claude account with subscription</b>, approve in the browser window that opens, then type <code>/exit</code>.</li>
          <li>Restart Job Scanner (close its window and run start.bat again), then click <b>Test it</b>.</li>
        </ol></details>
        ${a.backend === "cli" ? `<p class="note">Job Scanner runs Claude Code on this computer, so its analysis counts against your Claude Pro or Max plan's usage, not a separate bill.</p>` : `
        <ol class="steps">
          <li>Install Claude Code: <code>npm install -g @anthropic-ai/claude-code</code> (or the installer from claude.com/claude-code).</li>
          <li>In a terminal, run <code>claude</code> once and sign in with your Claude account (Pro or Max).</li>
          <li>Restart Job Scanner. To check, run <code>python -m job_scanner doctor</code>.</li>
        </ol>
        <p class="note">Running it as a service or in Docker? Run <code>claude setup-token</code> and put the token in <code>.env</code> as <code>CLAUDE_CODE_OAUTH_TOKEN</code>.</p>`}
        <h3>How much Claude does on its own</h3>
        <label class="f"><input type="checkbox" id="auto" ${s.auto_analyze ? "checked" : ""}> Ask Claude automatically when I open a posting</label>
        <div class="grid2">
          <label class="f">Only if the quick score is at least <input type="number" id="minscore" min="0" max="100" value="${s.auto_min_score}"></label>
          <label class="f">At most this many calls a day <small>0 = no limit</small><input type="number" id="limit" min="0" max="1000" value="${s.ai_daily_limit}"></label>
        </div>
        <h3>Which Claude model does what</h3>
        <div class="grid2">
          <label class="f">Reading postings, letters, résumés <select id="model_main">${modelOpts(s.model_main, "Claude Code's default")}</select></label>
          <label class="f">Quick jobs (employer reads, title ideas) <select id="model_light">${modelOpts(s.model_light, "Same as above")}</select></label>
        </div>
        <label class="f">Automatic reads (when you open a posting) use <select id="model_auto"><option value="main" ${s.model_auto !== "light" ? "selected" : ""}>the main model</option><option value="light" ${s.model_auto === "light" ? "selected" : ""}>the quick-jobs model (uses less of your plan)</option></select></label>
        <p class="note">Haiku is fastest and uses the least of your plan's limits; Opus is the most thorough. Scores are held to the same rubric either way.</p>
        ${s.startup_supported ? `<label class="f"><input type="checkbox" id="startup" ${s.start_with_windows ? "checked" : ""}> Start Job Scanner (hidden) when I sign in to Windows</label>` : ""}
        <button class="btn" id="save-ai">Save</button>
        <p class="note">Used today: ${usage.today.calls} calls (${usage.today.tokens.toLocaleString()} tokens). This week: ${usage.week.calls} calls.</p>
      </div>
      <div class="card"><h2>2. The Chrome extension</h2>
        <div id="ext-connect">${extensionInstalled() ? `<p><b>The extension is installed${S.extension_seen ? " and connected" : ""}.</b> ${S.extension_seen ? "" : "Click below to connect it to this app."}</p>
          <button class="btn ${S.extension_seen ? "" : "primary"}" id="pair">${S.extension_seen ? "Connect it again" : "Connect the extension"}</button> <span class="note" id="pair-out"></span>`
          : onThisComputer() ? `<p class="note">Not installed in this browser yet. Add it with the steps below; then reload this page and one click connects it.</p>`
          : `<p class="note">Job Scanner is running on another machine, so connect the extension by hand with the steps below.</p>`}</div>
        <details ${extensionInstalled() ? "" : "open"}><summary>Install it, or connect by hand</summary>
        <ol class="steps">
          <li>Open <code>chrome://extensions</code> and turn on <b>Developer mode</b>.</li>
          <li>Click <b>Load unpacked</b> and choose the <code>extension</code> folder inside Job Scanner.</li>
          <li>Click the Job Scanner icon in Chrome's toolbar, then <b>Settings</b>.${onThisComputer() ? "" : ` Set the app address to <code>${esc(location.origin)}</code> (one-click connecting only works when the app runs on the same computer as Chrome).`} Paste this pairing token and click <b>Save &amp; test</b>.</li>
        </ol>
        <div class="token"><input id="token" readonly value="${esc(token)}"><button class="btn" id="copy">Copy</button></div>
        <p class="note">Then browse LinkedIn, Indeed or NCWorks. Cards get a fit stamp, and a panel in the corner shows the posting you have open. On any other career site, click <b>Scan this page</b> in the extension.</p>
        <button class="btn small" id="rotate">Make a new token</button></details>
      </div>
    </div>
    ${phoneCard(s)}
    <div class="card"><h2>Getting started guide</h2><p class="note">The step-by-step guide from your first visit. Everything in it can be changed any time.</p><button class="btn" id="guide-again">Show the guide</button></div>
    <div class="card"><h2>Your data is backed up</h2><p class="note">Every day the app copies your data to a <code>backups</code> folder inside your data folder (the last 14 days are kept).</p><button class="btn small" id="backup-now">Back up now</button> <span class="note" id="backup-out"></span></div>
    <div class="card"><h2>Can the extension read each site?</h2>${healthList()}</div>
    <div class="card"><h2>Your data</h2>
      <p class="note">${S.counts.total} jobs, ${S.counts.analyzed} read by Claude. Everything is stored on this computer.</p>
      <div class="actions"><a class="btn" href="/api/jobs.csv">Export CSV</a><button class="btn" id="rescore">Rescore all jobs</button><button class="btn danger" id="clear">Clear jobs I'm not tracking</button></div>
    </div>`;
  $("#guide-again").addEventListener("click", () => tour.open(true));
  bindPhone();
  $("#backup-now").addEventListener("click", async () => {
    const out = await api("/api/backup", {}).catch((e) => ({ error: e.message }));
    $("#backup-out").textContent = out.error || (out.backup ? `Saved to ${out.backup}` : `Today's backup is already in ${out.folder}`);
  });
  const pair = $("#pair");
  if (pair) pair.addEventListener("click", () => {
    pair.disabled = true;
    $("#pair-out").textContent = "Connecting…";
    const done = (e) => {
      if (e.source !== window || !e.data || e.data.type !== "job-scanner-paired") return;
      removeEventListener("message", done);
      pair.disabled = false;
      $("#pair-out").textContent = e.data.ok ? "Connected. Browse LinkedIn or Indeed and jobs will appear." : e.data.error || "It didn't connect.";
      if (e.data.ok) { S.extension_seen = new Date().toISOString(); tour.refresh(); }
    };
    addEventListener("message", done);
    postMessage({ type: "job-scanner-pair", token: $("#token").value }, location.origin);
    setTimeout(() => { if (pair.disabled) { pair.disabled = false; $("#pair-out").textContent = "No answer from the extension. Reload this page and try again."; } }, 8000);
  });
  $("#copy").addEventListener("click", async () => { await navigator.clipboard.writeText($("#token").value); toast("Copied."); });
  $("#test-ai").addEventListener("click", async (e) => {
    e.target.disabled = true;
    $("#test-out").innerHTML = `<span class="spinner"></span>Asking Claude…`;
    const r = await api("/api/ai/test", {}).catch((err) => ({ ok: false, error: err.message }));
    $("#test-out").textContent = r.ok ? "Claude answered. It's working on your subscription." : r.error;
    $("#test-out").className = "note" + (r.ok ? " ok" : " warn");
    e.target.disabled = false;
  });
  $("#rotate").addEventListener("click", async () => {
    if (!confirm("Make a new token? The extension will need the new one.")) return;
    $("#token").value = (await api("/api/token/rotate", {})).token;
  });
  $("#save-ai").addEventListener("click", async () => {
    try {
      const body = { auto_analyze: $("#auto").checked, auto_min_score: $("#minscore").value, ai_daily_limit: $("#limit").value,
        model_main: $("#model_main").value, model_light: $("#model_light").value, model_auto: $("#model_auto").value };
      if ($("#startup")) body.start_with_windows = $("#startup").checked;
      const out = await api("/api/settings", body);
      S.settings = out.settings;
      toast("Saved.");
    } catch (err) { toast(err.message); }
  });
  $("#rescore").addEventListener("click", async () => toast(`Rescored ${(await api("/api/rescore", {})).rescored} jobs.`));
  $("#clear").addEventListener("click", async () => {
    if (!confirm("Remove every job you haven't saved, applied to or otherwise tracked?")) return;
    toast(`Removed ${(await api("/api/jobs/clear", { keep_tracked: true })).removed} jobs.`);
    await loadState();
  });
}

loadState().then(route).then(() => setTimeout(() => tour.open(false), 400)).catch((e) => { view.innerHTML = `<div class="card">Can't reach Job Scanner: ${esc(e.message)}</div>`; });
