/* Job Scanner web app, part two: Home, Discover, the résumé check, interview prep and the getting-started guide.
   Loaded after app.js and uses its helpers ($, api, esc, toast, S, view, list, money). */
"use strict";

/* ---------- what's set up ---------- */
function extensionInstalled() { return document.documentElement.dataset.jobScannerExtension || ""; }
function setupState() {
  const p = S.profile;
  const steps = [
    { id: "resume", label: "Add your résumé", done: p.resumes.length > 0, href: "#profile", where: "Profile",
      why: "Upload or paste it. Claude reads it as evidence of what you've done, and suggests titles and skills from it." },
    { id: "about", label: "Check your About me", done: !!(p.about_me || "").trim(), href: "#profile", where: "Profile",
      why: "Claude drafts it from your résumé. Add what you want next and what matters to you in a job." },
    { id: "prefs", label: "Choose your roles and location", done: p.target_titles.length > 0 && (p.locations.length > 0 || (p.remote || []).includes("remote")), href: "#profile", where: "Profile",
      why: "The job titles you want, where you'll work (or remote), your minimum pay and any dealbreakers." },
    { id: "claude", label: "Connect Claude", done: !!S.ai.backend, href: "#setup", where: "Setup",
      why: "Sign Claude Code in with your Claude subscription so it can read postings against your résumé." },
    { id: "extension", label: "Add the Chrome extension", done: !!(S.extension_seen || extensionInstalled()), href: "#setup", where: "Setup",
      why: "It reads the jobs you browse on LinkedIn, Indeed and career sites. One click connects it." },
  ];
  return { steps, done: steps.filter((s) => s.done).length };
}
function statusStrip() {
  const { steps } = setupState();
  const p = S.profile;
  const filled = [p.resumes.length, p.about_me, p.target_titles.length, p.skills.length, p.locations.length || (p.remote || []).includes("remote"), p.min_salary].filter(Boolean).length;
  const item = (ok, label, href) => `<a class="strip-item ${ok ? "ok" : "no"}" href="${href}">${ok ? "✓" : "!"} ${label}</a>`;
  const ext = steps.find((s) => s.id === "extension");
  return `<div class="strip">${item(!!S.ai.backend, S.ai.backend ? "Claude connected" : "Connect Claude", "#setup")}
    ${item(ext.done, ext.done ? "Extension connected" : "Connect the extension", "#setup")}
    ${item(filled >= 5, `Profile ${Math.round((100 * filled) / 6)}%`, "#profile")}</div>`;
}

/* ---------- home ---------- */
async function showHome() {
  const [{ todo }, ins, fr] = await Promise.all([api("/api/todo"), api("/api/insights").catch(() => null),
    api("/api/jobs?fresh=1&status=untracked&limit=40").catch(() => ({ jobs: [] }))]);
  const fresh = fr.jobs.filter((j) => j.best.verdict !== "Skip").slice(0, 6);
  const now = todo.filter((n) => n.urgency === "now");
  const w = ins && ins.week;
  const { steps, done } = setupState();
  const next = steps.find((s) => !s.done);
  const action = next ? { label: next.label, href: next.href, why: next.why }
    : now.length ? { label: `${now[0].title}: ${now[0].title_job || "a job"}`, href: `#job/${encodeURIComponent(now[0].key)}`, why: now[0].why }
    : w && w.best_unapplied && w.best_unapplied.length ? { label: `Look at ${w.best_unapplied[0].title}`, href: `#job/${encodeURIComponent(w.best_unapplied[0].key)}`, why: "Your best new match this week, not acted on yet." }
    : { label: "Find more roles that fit", href: "#discover", why: "Search links tuned to fresh postings, and roles your résumé fits that you may not be searching for." };
  const job = (j) => `<a href="#job/${encodeURIComponent(j.key)}">${esc(j.title || "?")}</a>${j.company ? ` <span class="note">at ${esc(j.company)}</span>` : ""}`;
  view.innerHTML = `<h1>Home</h1>
    ${statusStrip()}
    <div class="card next"><p class="note">Next step</p><h2><a href="${action.href}">${esc(action.label)} →</a></h2><p class="note">${esc(action.why)}</p>
      ${done < steps.length ? `<p class="note">Getting started: ${done} of ${steps.length} done. <a href="#" id="open-tour">Show the guide</a></p>` : ""}</div>
    ${fresh.length ? `<div class="card fresh-card"><h2>Posted in the last day</h2><p class="note">Applying in the first day or two gives you the best odds. These are worth a look now.</p>
      <ul class="clean">${fresh.map((j) => `<li><span class="score-chip ${j.best.verdict}">${j.best.score}</span> ${job(j)}</li>`).join("")}</ul>
      <p class="note"><a href="#jobs" id="all-fresh">All fresh jobs →</a></p></div>` : ""}
    <div class="grid2">
      <div class="card"><h2>Needs you today</h2>${now.length ? `<ul class="clean">${now.slice(0, 6).map((n) => `<li><b>${esc(n.title)}</b>: <a href="#job/${encodeURIComponent(n.key)}">${esc(n.title_job || "?")}</a></li>`).join("")}</ul>`
        : `<p class="note">Nothing due. When you save or apply to jobs, follow-ups and thank-yous show up here on the right day.</p>`}</div>
      <div class="card"><h2>Best new matches</h2>${w && w.best_unapplied.length ? `<ul class="clean">${w.best_unapplied.map((j) => `<li><span class="score-chip ${j.verdict}">${j.score}</span> ${job(j)}</li>`).join("")}</ul>`
        : `<p class="note">None this week yet. Browse LinkedIn or Indeed with the extension on, or open a search from <a href="#discover">Discover</a>; strong matches land here.</p>`}</div>
    </div>`;
  $("#all-fresh")?.addEventListener("click", () => { filters.fresh = "1"; });
  const t = $("#open-tour");
  if (t) t.addEventListener("click", (e) => { e.preventDefault(); tour.open(true); });
}

/* ---------- discover ---------- */
function searchTable(rows) {
  if (!rows.length) return `<p class="note">Add the job titles you want on your <a href="#profile">Profile</a> and search links appear here.</p>`;
  return `<table class="tbl searches"><tbody>${rows.map((r) => `<tr><td><b>${esc(r.title)}</b>${r.place ? `<br><span class="note">${esc(r.place)}</span>` : ""}</td>
    <td>${r.links.map((l) => `<a class="btn small" href="${esc(l.url)}" target="_blank" rel="noopener" title="${esc(l.site)}: ${esc(l.label)}">${esc(l.site)} · ${esc(l.label)}</a>`).join(" ")}</td></tr>`).join("")}</tbody></table>`;
}
function rolesHtml(roles) {
  if (!roles) return `<p class="note">Claude reads your résumés and suggests titles your experience carries over to: neighbouring roles, other industries, and the same job under other names. Only from what your résumés show.</p>`;
  return `<p>${esc(roles.summary)}</p><ul class="clean roles">${roles.roles.map((r) => `<li><span class="tag ${r.fit === "strong" ? "fit" : ""}">${r.fit === "strong" ? "Strong fit" : "Stretch"}</span> <b>${esc(r.title)}</b>: ${esc(r.why)}${r.gap ? ` <span class="note">Missing: ${esc(r.gap)}</span>` : ""}</li>`).join("")}</ul>
    <p class="note">Suggested ${esc((roles.at || "").slice(0, 10))}. Add any you like to your target roles on your Profile so they're scored as wanted.</p>`;
}
function learnedHtml(d) {
  const sug = d.suggestions.map((s) => `<li data-id="${esc(s.id)}" data-label="${esc(s.label)}">You've passed on <b>${esc(s.label)}</b> ${s.passed} times${s.kept ? ` (kept ${s.kept})` : ""}. Score them lower?
    <button class="btn small" data-act="yes">Yes</button> <button class="btn small" data-act="no">No, keep them</button></li>`).join("");
  const rules = d.learned.map((r) => `<li data-id="${esc(r.kind + ":" + r.value)}">Scoring lower: ${esc(r.label)} <button class="btn small" data-act="forget">Undo</button></li>`).join("");
  return (sug || rules) ? `<ul class="clean learn">${sug}${rules}</ul>` : `<p class="note">When you mark jobs Dismissed, patterns you keep passing on (an employer, a word in the title, staffing agencies, on-site work) show up here as suggestions. Nothing changes unless you say yes.</p>`;
}
async function showDiscover() {
  const d = await api("/api/discover");
  view.innerHTML = `<h1>Discover</h1><p class="lede">Better places to look. These open in your browser, and the extension reads what you see. Job sites are never searched behind your back.</p>
    <div class="card"><h2>Roles you'd fit but aren't searching for</h2><div id="roles">${rolesHtml(d.roles)}</div>
      <div class="actions"><button class="btn primary" id="get-roles" ${S.ai.backend ? "" : "disabled"}>${d.roles ? "Suggest again" : "Suggest roles from my résumés"}</button></div>
      <div id="role-searches">${d.roles ? searchTable(d.role_searches) : ""}</div></div>
    <div class="card"><h2>Fresh searches for your target roles</h2><p class="note">Newest first, limited to the last day or week, in the places and arrangements on your Profile, with your avoid-list words left out. Open the last-24-hours ones daily: early applicants get read.</p>${searchTable(d.searches)}</div>
    <div class="card"><h2>Learned from your passes</h2><div id="learned">${learnedHtml(d)}</div></div>`;
  $("#get-roles").addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.innerHTML = `<span class="spinner"></span>Claude is reading your résumés…`;
    try {
      const out = await api("/api/discover/roles", {});
      $("#roles").innerHTML = rolesHtml(out.roles);
      $("#role-searches").innerHTML = searchTable(out.role_searches);
      e.target.textContent = "Suggest again";
    } catch (err) { toast(err.message); e.target.textContent = "Suggest roles from my résumés"; }
    e.target.disabled = false;
  });
  bindLearned(d);
}
function bindLearned() {
  $("#learned").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const li = b.closest("li");
    const act = b.dataset.act;
    const body = act === "forget" ? { id: li.dataset.id, forget: true } : { id: li.dataset.id, accept: act === "yes", label: li.dataset.label };
    try {
      const out = await api("/api/learn", body);
      $("#learned").innerHTML = learnedHtml(out);
      toast(act === "yes" ? "Done: those jobs now score lower, with a note saying why." : act === "forget" ? "Undone." : "Got it, they'll be left alone.");
    } catch (err) { toast(err.message); }
  });
}

/* ---------- résumé check (on Insights) ---------- */
async function resumeCheckCard() {
  const el = $("#resume-check");
  if (!el) return;
  const d = await api("/api/resume-check").catch(() => null);
  if (!d || !d.resumes.length) { el.innerHTML = `<h2>Résumé check</h2><p class="note">Add a résumé on your <a href="#profile">Profile</a> to check it.</p>`; return; }
  el.innerHTML = `<h2>Résumé check</h2><p class="note">What application systems (ATS) need to read a résumé, and what your target jobs keep asking for. Plain rules, checked on this computer.</p>
    ${d.resumes.map((r) => `<h3>${esc(r.name)} <span class="score-chip ${r.score >= 80 ? "Apply" : r.score >= 60 ? "Consider" : "Skip"}">${r.score}%</span></h3>
      ${r.fix.length ? `<b>To fix</b>${list(r.fix)}` : ""}<details><summary>What's already right (${r.good.length})</summary>${list(r.good)}</details>`).join("")}
    ${d.resumes[0].keywords.length ? `<h3>Asked for by your jobs, missing from every résumé</h3><p>${d.resumes[0].keywords.map((k) => `<span class="tag">${esc(k.term)} <small>${k.jobs}</small></span>`).join("")}</p>
      <p class="note">Only add one if it's true for you: a résumé that claims a skill you lack costs you in the interview.</p>` : ""}`;
}

/* ---------- interview prep (on a job's page) ---------- */
function interviewHtml(key, j) {
  const p = j.interview;
  const head = `<h2 id="interview-card">Interview prep</h2>`;
  if (!p) return head + `<p class="note">Likely questions for this job with answers drawn from your résumés, what to brush up on, and good questions to ask them.</p>
    <button class="btn ${j.status === "interviewing" ? "primary" : ""}" id="prep" ${S.ai.backend ? "" : "disabled"}>Prepare me</button>`;
  return head + `<p class="note">Prepared ${esc((p.at || "").slice(0, 10))}. Answers use only what your résumés show; practise them out loud in your own words.</p>
    ${p.questions.map((q) => `<details class="q"><summary>${esc(q.question)}${q.from_resume ? "" : ` <span class="tag warn">not on your résumé</span>`}</summary>
      <p class="note">${esc(q.why)}</p><p>${esc(q.answer)}</p></details>`).join("")}
    <div class="grid2"><div><h3>Brush up on</h3>${list(p.topics)}</div><div><h3>Ask them</h3>${list(p.ask_them)}</div></div>
    <h3>Look up first</h3>${list(p.research)}
    <button class="btn small" id="prep">Prepare again</button>`;
}
function bindInterview(key) {
  const b = $("#prep");
  if (!b) return;
  b.addEventListener("click", async () => {
    b.disabled = true;
    b.innerHTML = `<span class="spinner"></span>Claude is preparing your interview…`;
    try {
      const out = await api(`/api/jobs/${encodeURIComponent(key)}/interview`, {});
      $("#interview").innerHTML = interviewHtml(key, out.job);
    } catch (err) { toast(err.message); }
    bindInterview(key);
  });
}

/* ---------- the getting-started guide ---------- */
const tour = (() => {
  let box = null, i = 0, hidden = false;
  function render() {
    const { steps, done } = setupState();
    if (done === steps.length && box) { finish(true); toast("You're all set. Everything can still be changed on Profile and Setup."); return; }
    const s = steps[i];
    box.innerHTML = `<div class="tour-head"><b>Getting started</b> <span class="note">${done} of ${steps.length} done</span></div>
      <ol class="tour-steps">${steps.map((x, n) => `<li class="${x.done ? "done" : ""} ${n === i ? "on" : ""}" data-n="${n}">${x.done ? "✓ " : ""}${esc(x.label)}</li>`).join("")}</ol>
      <p>${esc(s.why)}</p><p class="note">You can change this any time on ${esc(s.where)}.</p>
      <div class="actions"><a class="btn primary small" href="${s.href}" id="tour-go">${s.done ? "Look again" : "Do this now"}</a>
        <button class="btn small" id="tour-next">${i < steps.length - 1 ? "Next step" : "Finish"}</button></div>
      <div class="tour-foot"><a href="#" id="tour-skip">Skip for now</a> · <a href="#" id="tour-never">Don't show this again</a></div>`;
    box.querySelector("#tour-next").onclick = () => { if (i < steps.length - 1) { i += 1; render(); } else finish(true); };
    box.querySelector("#tour-skip").onclick = (e) => { e.preventDefault(); finish(false); };
    box.querySelector("#tour-never").onclick = (e) => { e.preventDefault(); finish(true); };
    box.querySelectorAll(".tour-steps li").forEach((li) => (li.onclick = () => { i = +li.dataset.n; render(); }));
  }
  async function finish(forever) {
    if (box) { box.remove(); box = null; }
    hidden = true;
    if (forever) { S.settings.tour_done = true; await api("/api/settings", { tour_done: true }).catch(() => {}); }
  }
  return {
    open(force) {
      if (!force && (hidden || S.settings.tour_done)) return;
      hidden = false;
      if (!box) { box = document.createElement("aside"); box.className = "tour card"; document.body.appendChild(box); }
      const { steps } = setupState();
      i = Math.max(0, steps.findIndex((s) => !s.done));
      render();
    },
    refresh() { if (box) render(); },
  };
})();
