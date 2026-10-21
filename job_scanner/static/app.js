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
}
const profileEmpty = () => !(S.profile.target_titles.length || S.profile.skills.length || S.profile.resume || S.profile.about_me);

/* ---------- routing ---------- */
async function route() {
  const hash = decodeURIComponent(location.hash.slice(1)) || (S && profileEmpty() ? "profile" : "jobs");
  const [name, ...rest] = hash.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === (name === "job" ? "jobs" : name)));
  try {
    if (name === "job") return await showJob(rest.join("/"));
    if (name === "tracker") return await showTracker();
    if (name === "week") return await showWeek();
    if (name === "profile") return showProfile();
    if (name === "setup") return await showSetup();
    return await showJobs();
  } catch (e) {
    view.innerHTML = `<div class="card"><p>${esc(e.message)}</p></div>`;
  }
}
addEventListener("hashchange", route);

/* ---------- jobs ---------- */
const filters = { text: "", source: "", verdict: "", sort: "score", status: "", remote: "", min_pay: "", max_years: "", degree: "", clearance: "" };
const FILTER_SELECTS = ["source", "verdict", "sort", "remote", "max_years", "degree", "clearance"];
const factTags = (j) => (j.fact_tags || []).map((t) => `<span class="tag fact">${esc(t)}</span>`).join("");
const EMPLOYER_TAG = { "staffing or recruiting agency": "Staffing agency", "agency hiring for an unnamed client": "Agency, client unnamed" };
function historyTags(j) {
  const emp = j.employer && j.employer.read && EMPLOYER_TAG[j.employer.read.employer_type];
  return (!j.status && j.copy_status ? `<span class="tag st">${esc(STATUS_LABEL[j.copy_status.status])} on ${esc(j.copy_status.on)}</span>` : "")
    + (j.copies && j.copies.length ? `<span class="tag">Also on ${esc([...new Set(j.copies.map((c) => c.source_name))].join(", "))}</span>` : "")
    + (j.repost ? `<span class="tag warn" title="Reposted ${j.repost.count}x since ${esc(j.repost.since)}">Reposted${j.repost.count > 1 ? " " + j.repost.count + "x" : ""}</span>` : "")
    + (emp ? `<span class="tag warn">${esc(emp)}</span>` : "");
}
const SITE_CHECK = { posting: "postings", cards: "search results" };
function healthWarning() {
  const bad = [];
  for (const [src, checks] of Object.entries(S.site_health || {})) {
    for (const [what, e] of Object.entries(checks)) if (!e.ok) bad.push(`${esc(S.sources[src] || src)} ${SITE_CHECK[what] || what} (since ${esc(e.at.slice(0, 10))})`);
  }
  return bad.length ? `<div class="card warn"><b>Job Scanner can't read ${bad.join(", ")}.</b> The site has probably changed its pages.
    Open one of those pages, click the extension, then <b>Copy diagnostics for this page</b>, and paste it into an issue or to Claude so the reader can be fixed.</div>` : "";
}
function jobRow(j) {
  const b = j.best, r = j.rules || {};
  const why = j.ai ? j.ai.summary : [...(r.reasons || []).slice(0, 2), ...(r.cautions || []).slice(0, 2)].join(" · ");
  const pay = j.pay_text || (r.pay_max ? `up to ${money(r.pay_max)}` : "");
  return `<article class="job" data-key="${esc(j.key)}">
    <div class="score ${b.verdict}">${b.score}<small>${b.by === "ai" ? "✦ " : ""}${b.verdict}</small></div>
    <div><div class="t">${esc(j.title || "(untitled)")}</div>
      <div class="m">${esc([j.company, j.location, pay].filter(Boolean).join(" · "))}</div>
      <div class="why">${esc(why)}</div>
      <div>${j.status ? `<span class="tag st">${esc(STATUS_LABEL[j.status])}</span>` : ""}<span class="tag">${esc(j.source_name)}</span>${r.remote ? `<span class="tag">${esc(r.remote)}</span>` : ""}${factTags(j)}${historyTags(j)}${j.description ? "" : `<span class="tag">card only</span>`}${j.easy_apply ? `<span class="tag">Easy Apply</span>` : ""}</div>
    </div>
    <div class="side m">${esc((j.last_seen || "").slice(0, 10))}</div>
  </article>`;
}
function bindRows(root) {
  root.querySelectorAll(".job").forEach((el) => el.addEventListener("click", () => (location.hash = "job/" + encodeURIComponent(el.dataset.key))));
}
async function showJobs() {
  const sources = Object.entries(S.sources).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  view.innerHTML = `
    <h1>Jobs</h1>
    <p class="lede">Every posting the extension has read, best fit first. ✦ marks Claude's assessment of the full posting against your résumé. The rest are quick matches to your preferences, which don't judge your chances.</p>
    ${profileEmpty() ? `<div class="card"><b>Start with your Profile.</b> Add the roles you want, your skills and your résumé so the scores mean something. <a href="#profile">Fill it in</a></div>` : ""}
    ${healthWarning()}
    ${S.ai.limited ? `<div class="card warn">${esc(S.ai.limited)} Automatic reads are paused until then.</div>` : ""}
    <div class="toolbar">
      <input type="search" id="q" placeholder="Search title, company, location" value="${esc(filters.text)}">
      <select id="source"><option value="">All sites</option>${sources}</select>
      <select id="verdict"><option value="">Any verdict</option><option>Apply</option><option>Consider</option><option>Skip</option></select>
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
const list = (items, fn = esc) => items && items.length ? `<ul class="clean">${items.map((x) => `<li>${fn(x)}</li>`).join("")}</ul>` : `<p class="note">None.</p>`;
async function showJob(key) {
  const { job: j, ai_current } = await api("/api/jobs/" + encodeURIComponent(key));
  const b = j.best, r = j.rules || {}, ai = j.ai;
  const statusOpts = S.statuses.map((s) => `<option value="${s}" ${s === (j.status || "") ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("");
  view.innerHTML = `
    <p><a href="#jobs">← All jobs</a></p>
    <div class="card detail-head">
      <div class="score ${b.verdict}">${b.score}<small>${b.by === "ai" ? "✦ " : ""}${b.verdict}</small></div>
      <div style="flex:1">
        <h1>${esc(j.title)}</h1>
        <div class="m">${esc([j.company, j.location, j.pay_text || (r.pay_max ? "up to " + money(r.pay_max) : ""), j.job_type].filter(Boolean).join(" · "))}</div>
        <div>${factTags(j)}${historyTags(j)}${r.remote ? `<span class="tag">${esc(r.remote)}</span>` : ""}${(j.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}<span class="tag">${esc(j.source_name)}</span>${j.posted_text ? `<span class="tag">${esc(j.posted_text)}</span>` : ""}${j.applicants ? `<span class="tag">${j.applicants}+ applicants</span>` : ""}</div>
        <div class="actions">${j.url ? `<a class="btn primary" href="${esc(j.url)}" target="_blank" rel="noopener">Open posting</a>` : ""}
          <button class="btn" id="analyze">${ai ? "Ask Claude again" : "Ask Claude about this job"}</button></div>
        <p class="note" id="ai-note">${ai && !ai_current ? "Your profile or this posting changed since Claude read it. Ask again for a fresh take." : ""}${!j.description ? " Only the search card was captured: open the posting with the extension on for Claude to read the full description." : ""}</p>
      </div>
    </div>
    <div class="grid2">
      <div>
        <div class="card" id="ai-card">${ai ? aiHtml(ai) : `<h2>Claude's take</h2><p class="note">${S.ai.backend ? "Not asked yet. Click Ask Claude to get a fit score, your strengths and gaps for this role, red flags and résumé tips." : "Set up Claude on the Setup page to get a full analysis on your Claude subscription."}</p>`}</div>
        <div class="card" id="tailor-card">${tailorHtml(j)}</div>
        <div class="card"><h2>Quick match: ${r.score} (${r.verdict})</h2><p class="note">How well the posting matches your stated preferences. It doesn't judge your chances; Claude's take does.</p><h3>Good</h3>${list(r.reasons)}<h3>Watch out</h3>${list(r.cautions)}</div>
      </div>
      <div>
        <div class="card">
          <h2>Tracking</h2>
          <label class="f">Status <select id="status">${statusOpts}</select></label>
          <div class="grid2"><label class="f">Applied on <input type="date" id="applied_at" value="${esc(j.applied_at || "")}"></label>
          <label class="f">Follow up on <input type="date" id="follow_up" value="${esc(j.follow_up || "")}"></label></div>
          <label class="f">Notes <textarea id="notes" placeholder="Recruiter name, referral, what you sent…">${esc(j.notes || "")}</textarea></label>
          <div class="actions"><button class="btn primary" id="save">Save</button><button class="btn danger" id="del">Delete job</button></div>
        </div>
        ${j.copies && j.copies.length ? `<div class="card"><h2>Also posted on</h2><ul class="clean">${j.copies.map((c) => `<li><a href="#job/${encodeURIComponent(c.key)}">${esc(c.source_name)}</a>${c.url ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener">open</a>` : ""}${c.status ? ` · ${esc(STATUS_LABEL[c.status])}` : ""} <span class="note">first seen ${esc((c.first_seen || "").slice(0, 10))}</span></li>`).join("")}</ul>
          <p class="note">The same job on another site. Track it on one of them; the status shows on every copy's card.</p></div>` : ""}
        <div class="card" id="employer-card">${employerHtml(j)}</div>
        <div class="card">
          <h2>Cover letter</h2>
          <label class="f">Anything to mention? <small>Optional: a referral, why this company, what to emphasise</small><textarea id="letter-notes" style="min-height:70px"></textarea></label>
          <div class="actions"><button class="btn" id="letter">${j.cover_letter ? "Write another" : "Write a cover letter"}</button>${j.cover_letter ? `<button class="btn" id="copy-letter">Copy</button>` : ""}</div>
          ${j.cover_letter ? `<div class="letter card" style="margin-top:12px">${esc(j.cover_letter.text)}</div>` : ""}
        </div>
      </div>
    </div>
    ${j.description ? `<div class="card"><h2>The posting</h2><div class="desc">${esc(j.description)}</div></div>` : ""}`;

  $("#analyze").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>Claude is reading the posting…`;
    try { await api(`/api/jobs/${encodeURIComponent(key)}/analyze`, { force: true }); await showJob(key); }
    catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Ask Claude about this job"; }
  });
  $("#save").addEventListener("click", async () => {
    try {
      await api(`/api/jobs/${encodeURIComponent(key)}/update`, { status: $("#status").value, applied_at: $("#applied_at").value, follow_up: $("#follow_up").value, notes: $("#notes").value });
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
    try { await api(`/api/jobs/${encodeURIComponent(key)}/cover-letter`, { notes: $("#letter-notes").value }); await showJob(key); }
    catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Write a cover letter"; }
  });
  const busyButton = (id, label, path, after) => {
    const b = $(id);
    if (!b) return;
    b.addEventListener("click", async () => {
      b.disabled = true;
      b.innerHTML = `<span class="spinner"></span>${label}`;
      try { await api(path, {}); await showJob(key); }
      catch (err) { toast(err.message); b.disabled = false; b.textContent = after; }
    });
  };
  busyButton("#tailor", "Claude is comparing…", `/api/jobs/${encodeURIComponent(key)}/tailor`, "Try again");
  busyButton("#employer", "Claude is reading their postings…", `/api/jobs/${encodeURIComponent(key)}/employer`, "Try again");
  const copy = $("#copy-letter");
  if (copy) copy.addEventListener("click", async () => { await navigator.clipboard.writeText(j.cover_letter.text); toast("Copied."); });
}
function tailorHtml(j) {
  const t = j.tailoring;
  const btn = `<button class="btn" id="tailor" ${S.ai.backend ? "" : "disabled"}>${t ? "Compare again" : "Compare my résumé to this job"}</button>`;
  if (!t) return `<h2>Fit your résumé to this job</h2><p class="note">Claude lists what the posting asks for that your résumé doesn't show, and rewords lines you already have to match its language. It never adds experience you don't have.</p><div class="actions">${btn}</div>`;
  return `<h2>Fit your résumé to this job</h2><p>${esc(t.summary)}</p>
    <h3>What it asks for that your résumé doesn't show</h3>${list(t.missing, (x) => `<span class="sev ${x.importance === "required" ? "major" : "minor"}">${esc(x.importance)}</span><b>${esc(x.requirement)}</b>. ${esc(x.advice)}`)}
    <h3>Lines to reword</h3>${t.rewrites && t.rewrites.length ? t.rewrites.map((x) => `<div class="rewrite"><div class="was">${esc(x.original)}</div><div class="now">${esc(x.suggested)}</div><p class="note">${esc(x.why)}</p></div>`).join("") : `<p class="note">None worth changing.</p>`}
    <h3>Keywords</h3><div>${(t.keywords_present || []).map((k) => `<span class="tag st">${esc(k)}</span>`).join("")}${(t.keywords_missing || []).map((k) => `<span class="tag" title="Not on your résumé. Add only if true.">+ ${esc(k)}</span>`).join("")}</div>
    <p class="note">Green: already on your résumé. +: missing, worth adding only if it's true. Rewrites that weren't copied from your résumé, or that added a number, were dropped. Compared ${esc((t.at || "").slice(0, 10))}.</p>
    <div class="actions">${btn}</div>`;
}
function employerHtml(j) {
  const e = j.employer, rd = e && e.read;
  const btn = j.company ? `<button class="btn small" id="employer" ${S.ai.backend ? "" : "disabled"}>${rd ? "Read again" : "Read this employer's postings"}</button>` : "";
  if (!rd) return `<h2>The employer</h2><p class="note">${j.company ? `Claude reads the postings you've seen from ${esc(j.company)} (up to five) and says what they show: direct employer or agency, warning signs, and what to check yourself. It's done once and reused for all their jobs.` : "This posting doesn't name an employer."}</p><div class="actions">${btn}</div>`;
  return `<h2>The employer: ${esc(e.name)}</h2><p><span class="tag ${EMPLOYER_TAG[rd.employer_type] ? "warn" : ""}">${esc(rd.employer_type)}</span></p><p>${esc(rd.summary)}</p>
    ${rd.signals && rd.signals.length ? `<h3>What their postings show</h3>${list(rd.signals)}` : ""}
    ${rd.concerns && rd.concerns.length ? `<h3>Concerns</h3>${list(rd.concerns)}` : ""}
    ${rd.verify && rd.verify.length ? `<h3>Check for yourself</h3>${list(rd.verify)}` : ""}
    <p class="note">From ${e.postings} of their postings, ${esc((e.at || "").slice(0, 10))}. Only what the postings say: no reviews or news.</p><div class="actions">${btn}</div>`;
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
    <h3>Résumé tips</h3>${list(ai.resume_tips)}
    ${ai.tailored_bullets && ai.tailored_bullets.length ? `<h3>Bullets tailored to this job</h3>${list(ai.tailored_bullets)}` : ""}
    ${ai.keywords && ai.keywords.length ? `<h3>Keywords to include (if true)</h3><div>${ai.keywords.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div>` : ""}
    ${ai.questions_to_ask && ai.questions_to_ask.length ? `<h3>Questions to ask them</h3>${list(ai.questions_to_ask)}` : ""}
    ${ai.salary_note ? `<h3>Pay</h3><p>${esc(ai.salary_note)}</p>` : ""}
    <p class="note">Read ${esc((ai.at || "").slice(0, 10))}</p>`;
}

/* ---------- tracker ---------- */
async function showTracker() {
  const [out, tr] = await Promise.all([api("/api/jobs?status=tracked&sort=newest&dupes=1"), api("/api/tracker")]);
  const cols = ["saved", "applied", "interviewing", "offer"];
  const by = (s) => out.jobs.filter((j) => j.status === s);
  const closed = out.jobs.filter((j) => ["rejected", "withdrawn"].includes(j.status));
  const today = new Date().toISOString().slice(0, 10);
  const due = tr.due;
  const mini = (j) => `<article class="job" data-key="${esc(j.key)}"><div><div class="t">${esc(j.title)}</div><div class="m">${esc(j.company || "")}</div>
    <div class="m">${j.best.by === "ai" ? "✦ " : ""}${j.best.verdict} ${j.best.score}${j.applied_at ? " · applied " + esc(j.applied_at) : ""}${j.follow_up ? " · follow up " + esc(j.follow_up) : ""}</div></div></article>`;
  view.innerHTML = `<h1>Tracker</h1><p class="lede">Your applications, from saved to offer. Change a job's status on its page, or with the buttons in the extension's panel.</p>
    ${due.length ? `<div class="card"><h2>Follow up now <span class="note">${due.length}</span></h2><p class="note">Applications waiting ${tr.follow_up_days}+ days, or past the follow-up date you set. A short, polite note to the recruiter or hiring manager is normal. Change the wait on the Setup page.</p><div class="jobs">${due.map(mini).join("")}</div></div>` : ""}
    <div class="board">${cols.map((c) => `<section class="col"><h2>${STATUS_LABEL[c]} <span>${by(c).length}</span></h2><div class="jobs">${by(c).map(mini).join("") || `<p class="note">None yet.</p>`}</div></section>`).join("")}</div>
    ${closed.length ? `<div class="card" style="margin-top:16px"><h2>Closed</h2><div class="jobs">${closed.map(mini).join("")}</div></div>` : ""}
    <div class="card" style="margin-top:16px"><h2>Your results by fit score</h2>
      <p class="note">How each job scored when you applied, and what came of it. It shows whether the scores mean anything for you. It doesn't change them.</p>
      <table class="results"><thead><tr><th>Score</th><th>Applied</th><th>Interviews</th><th>Offers</th><th>Rejected</th><th>Interview rate</th></tr></thead>
      <tbody>${tr.outcomes.bands.map((b) => `<tr><td>${esc(b.band)}</td><td>${b.applied}</td><td>${b.interviews}</td><td>${b.offers}</td><td>${b.rejected}</td><td>${b.applied ? Math.round((100 * b.interviews) / b.applied) + "%" : "—"}</td></tr>`).join("")}</tbody></table>
      <p>${esc(tr.outcomes.note)}</p></div>`;
  bindRows(view);
}

/* ---------- the week ---------- */
async function showWeek() {
  const d = await api("/api/digest");
  const row = (j, extra = "") => `<article class="job" data-key="${esc(j.key)}"><div class="score ${j.verdict}">${j.score}<small>${j.by === "ai" ? "✦ " : ""}${j.verdict}</small></div>
    <div><div class="t">${esc(j.title || "(untitled)")}</div><div class="m">${esc([j.company, j.source_name].filter(Boolean).join(" · "))}${extra}</div></div><div></div></article>`;
  const section = (title, items, fn, empty) => `<div class="card"><h2>${title} <span class="note">${items.length}</span></h2>${items.length ? `<div class="jobs">${items.map(fn).join("")}</div>` : `<p class="note">${empty}</p>`}</div>`;
  const u = d.usage;
  view.innerHTML = `<h1>This week</h1><p class="lede">Since ${esc(d.since)}: ${d.new_jobs} new jobs seen, ${d.read_by_claude} read by Claude.</p>
    ${section("Best matches you haven't acted on", d.best_unapplied, (j) => row(j), "Nothing new worth a look this week. Keep browsing with the extension on.")}
    ${section("Follow up", d.due, (j) => row(j, j.days_waiting != null ? ` · applied ${j.days_waiting} days ago` : ""), "No follow-ups due.")}
    <div class="grid2">
      ${section("Applications sent", d.applied, (j) => row(j), "None this week.")}
      ${section("Moved forward or closed", d.moved, (j) => row(j, ` · ${esc(STATUS_LABEL[j.status])}`), "No changes this week.")}
    </div>
    <div class="card"><h2>Claude usage</h2><p>This week: <b>${u.week.calls}</b> calls, ${u.week.tokens.toLocaleString()} tokens. Today: ${u.today.calls}${u.daily_limit ? ` of ${u.daily_limit} automatic reads allowed` : ""}.</p>
      <p class="note">These count against your Claude plan. Pick lighter models or a lower daily cap on the Setup page.</p></div>`;
  bindRows(view);
}

/* ---------- profile ---------- */
function showProfile() {
  const p = S.profile, c = S.choices;
  const checks = (name, opts, chosen) => `<div class="checks">${opts.map((o) => `<label><input type="checkbox" name="${name}" value="${o}" ${chosen.includes(o) ? "checked" : ""}> ${o}</label>`).join("")}</div>`;
  view.innerHTML = `<h1>Your profile</h1>
    <p class="lede">Everything here stays on this computer. The quick scores use your preferences; Claude reads all of it, including your résumé and About Me, when it judges a posting.</p>
    <form id="pf">
      <div class="grid2">
        <div class="card"><h2>What you're looking for</h2>
          <label class="f">Job titles you want <small>One per line, e.g. Data Analyst</small><textarea name="target_titles" style="min-height:90px">${esc(p.target_titles.join("\n"))}</textarea></label>
          <label class="f">Your skills <small>Comma or line separated: tools, certifications, specialties</small><textarea name="skills" style="min-height:90px">${esc(p.skills.join(", "))}</textarea></label>
          <label class="f">Locations <small>Cities you'd work in, one per line, e.g. Raleigh, NC</small><textarea name="locations" style="min-height:70px">${esc(p.locations.join("\n"))}</textarea></label>
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
          <div class="card"><h2>About me</h2>
            <label class="f">Name <small>Used on cover letters</small><input name="name" value="${esc(p.name)}"></label>
            <label class="f">About me <small>Who you are, what you want next, what you're good at, what matters to you in a job. The more Claude knows, the better its advice.</small><textarea name="about_me" style="min-height:180px">${esc(p.about_me)}</textarea></label>
          </div>
          <div class="card"><h2>Résumé</h2>
            <div class="actions" style="margin:0 0 10px"><label class="btn small">Upload PDF, Word or text<input type="file" id="resume-file" accept=".pdf,.docx,.txt,.md" hidden></label>
              <button class="btn small" type="button" id="suggest" ${S.ai.backend ? "" : "disabled"}>Suggest titles and skills from it</button></div>
            <p class="note" id="resume-note">${S.ai.backend ? "PDFs are read by Claude on your subscription." : "Word and text files are read here. PDFs need Claude set up; or paste the text."}</p>
            <textarea name="resume" style="min-height:260px" placeholder="Paste your résumé here">${esc(p.resume)}</textarea>
          </div>
        </div>
      </div>
      <div class="actions"><button class="btn primary" type="submit">Save profile</button></div>
    </form>`;
  const f = $("#pf");
  const collect = () => {
    const fd = new FormData(f);
    const out = {};
    for (const k of ["name", "about_me", "resume", "dealbreakers", "min_salary", "years_experience"]) out[k] = fd.get(k);
    for (const k of ["target_titles", "skills", "locations", "avoid_keywords"]) out[k] = fd.get(k);
    for (const k of ["remote", "job_types", "seniority"]) out[k] = fd.getAll(k);
    out.max_age_days = S.profile.max_age_days;
    return out;
  };
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const out = await api("/api/profile", { profile: collect() });
      S.profile = out.profile;
      toast(`Saved. ${out.counts.total} jobs rescored.`);
    } catch (err) { toast(err.message); }
  });
  $("#resume-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const note = $("#resume-note");
    note.innerHTML = `<span class="spinner"></span>Reading ${esc(file.name)}…`;
    const data = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(file); });
    try {
      const out = await api("/api/profile/resume-file", { filename: file.name, data });
      f.resume.value = out.resume_text;
      applySuggestions(out);
      note.textContent = "Read. Check it over, then Save profile.";
    } catch (err) { note.textContent = err.message; }
  });
  $("#suggest").addEventListener("click", async (e) => {
    e.target.disabled = true;
    const note = $("#resume-note");
    note.innerHTML = `<span class="spinner"></span>Claude is reading your résumé…`;
    try { applySuggestions(await api("/api/profile/suggest", { resume: f.resume.value })); note.textContent = "Added suggestions. Edit them, then Save profile."; }
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

/* ---------- setup ---------- */
const modelOpts = (chosen) => Object.entries(S.models).map(([k, v]) => `<option value="${k}" ${k === (chosen || "") ? "selected" : ""}>${esc(v)}</option>`).join("");
function siteHealthTable() {
  const rows = Object.entries(S.site_health || {}).flatMap(([src, checks]) => Object.entries(checks).map(([what, e]) =>
    `<li><b>${esc(S.sources[src] || src)} ${esc(SITE_CHECK[what] || what)}</b>: ${e.ok ? "read fine" : `<span class="warn-text">not readable</span> on ${esc(e.path || "?")}`} <span class="note">(${esc(e.at.slice(0, 16).replace("T", " "))})</span></li>`));
  return rows.length ? `<ul class="clean">${rows.join("")}</ul>` : `<p class="note">Nothing reported yet. Browse a job site with the extension on.</p>`;
}
async function showSetup() {
  const [{ token }, usage] = await Promise.all([api("/api/token"), api("/api/ai/usage")]);
  const a = S.ai, s = S.settings;
  view.innerHTML = `<h1>Setup</h1>
    <div class="grid2">
      <div class="card"><h2>1. Claude, on your subscription</h2>
        <p>Status: <b>${esc(a.label)}</b></p>
        ${a.limited ? `<p class="warn-text">${esc(a.limited)} Automatic reads are paused until then; Ask Claude still tries.</p>` : ""}
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
        <h3>Which Claude model</h3>
        <div class="grid2">
          <label class="f">Automatic reads <select id="model_auto">${modelOpts(s.model_auto)}</select></label>
          <label class="f">When you ask <small>Ask Claude, cover letters, résumé, employer</small><select id="model_ondemand">${modelOpts(s.model_ondemand)}</select></label>
        </div>
        <p class="note">Lighter models use less of your plan's usage, so more automatic reads fit in a day. Quick scores on search cards don't use Claude at all.</p>
        <label class="f">Remind me to follow up after this many days <input type="number" id="follow_up_days" min="1" max="60" value="${s.follow_up_days}"></label>
        <button class="btn" id="save-ai">Save</button>
        <p class="note">Used today: ${usage.today.calls} calls (${usage.today.tokens.toLocaleString()} tokens). This week: ${usage.week.calls} calls.</p>
      </div>
      <div class="card"><h2>2. The Chrome extension</h2>
        <ol class="steps">
          <li>Open <code>chrome://extensions</code> and turn on <b>Developer mode</b>.</li>
          <li>Click <b>Load unpacked</b> and choose the <code>extension</code> folder inside Job Scanner.</li>
          <li>Click the Job Scanner icon in Chrome's toolbar, then <b>Settings</b>. Paste this pairing token and click <b>Save &amp; test</b>.</li>
        </ol>
        <div class="token"><input id="token" readonly value="${esc(token)}"><button class="btn" id="copy">Copy</button></div>
        <p class="note">Then browse LinkedIn, Indeed or NCWorks. Cards get a fit stamp, and a panel in the corner shows the posting you have open. On any other career site, click <b>Scan this page</b> in the extension.</p>
        <button class="btn small" id="rotate">Make a new token</button>
      </div>
    </div>
    <div class="card"><h2>Reading the job sites</h2>
      ${siteHealthTable()}
      <p class="note">The extension reports here when it opens a posting or a page of search results it can't read, which usually means the site changed its pages.</p>
    </div>
    <div class="card"><h2>Your data</h2>
      <p class="note">${S.counts.total} jobs, ${S.counts.analyzed} read by Claude. Everything is stored on this computer.</p>
      <div class="actions"><a class="btn" href="/api/jobs.csv">Export CSV</a><button class="btn" id="rescore">Rescore all jobs</button><button class="btn danger" id="clear">Clear jobs I'm not tracking</button></div>
    </div>`;
  $("#copy").addEventListener("click", async () => { await navigator.clipboard.writeText($("#token").value); toast("Copied."); });
  $("#rotate").addEventListener("click", async () => {
    if (!confirm("Make a new token? The extension will need the new one.")) return;
    $("#token").value = (await api("/api/token/rotate", {})).token;
  });
  $("#save-ai").addEventListener("click", async () => {
    try {
      const out = await api("/api/settings", { auto_analyze: $("#auto").checked, auto_min_score: $("#minscore").value, ai_daily_limit: $("#limit").value,
        model_auto: $("#model_auto").value, model_ondemand: $("#model_ondemand").value, follow_up_days: $("#follow_up_days").value });
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

loadState().then(route).catch((e) => { view.innerHTML = `<div class="card">Can't reach Job Scanner: ${esc(e.message)}</div>`; });
