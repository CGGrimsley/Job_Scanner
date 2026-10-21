/* Job Scanner: background worker. Batches captured jobs to your Job Scanner app and relays the panel's requests. */
"use strict";

const DEFAULTS = { server: "http://127.0.0.1:8766", token: "", enabled: true, notify: true };
let queue = [];
let timer = null;
let retryDelay = 0;
const session = { sent: 0, alerts: 0, error: "" };
const perTab = new Map(); // tabId -> Set of job ids the app has accepted from that page

const settings = () => chrome.storage.local.get(DEFAULTS);

async function call(path, body) {
  const s = await settings();
  try {
    const res = await fetch(`${s.server}${path}`, body === undefined
      ? { headers: { "X-Scanner-Token": s.token } }
      : { method: "POST", headers: { "Content-Type": "application/json", "X-Scanner-Token": s.token }, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    return res.ok ? { ok: true, ...out } : { ok: false, error: out.error || `Job Scanner answered ${res.status}` };
  } catch (_) {
    return { ok: false, error: "Can't reach Job Scanner. Is the app running, and is its address in Settings right?" };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const tab = sender.tab ? sender.tab.id : null;
  if (msg.type === "capture") {
    queue.push(...msg.jobs.map((job) => ({ job, tab })));
    clearTimeout(timer);
    timer = setTimeout(flush, 1000);
  } else if (msg.type === "status") {
    reply(session);
  } else if (msg.type === "ping") {
    call("/api/capture/ping").then(reply);
    return true;
  } else if (msg.type === "get-job") {
    call(`/api/capture/job?source=${encodeURIComponent(msg.source)}&id=${encodeURIComponent(msg.id)}`).then(reply);
    return true;
  } else if (msg.type === "analyze") {
    settings().then((s) => {
      if (!s.enabled && msg.auto) return reply({ ok: false, error: "Paused." });
      call("/api/capture/analyze", { source: msg.source, id: msg.id, auto: !!msg.auto, force: !!msg.force }).then(reply);
    });
    return true; // Claude takes a little while
  } else if (msg.type === "cover-letter") {
    call("/api/capture/cover-letter", { source: msg.source, id: msg.id }).then(reply);
    return true;
  } else if (msg.type === "easy-apply") {
    call("/api/capture/easy-apply", { source: msg.source, id: msg.id }).then(reply);
    return true; // several Claude calls: a minute or two
  } else if (msg.type === "fill-tab") {
    fillTab(msg.tabId).then(reply);
    return true;
  } else if (msg.type === "answer-tab") {
    answerTab(msg.tabId).then(reply);
    return true;
  } else if (msg.type === "set-status") {
    call("/api/capture/status", { source: msg.source, id: msg.id, status: msg.status }).then(reply);
    return true;
  } else if (msg.type === "open-app") {
    settings().then((s) => chrome.tabs.create({ url: `${s.server}/#job/${encodeURIComponent(msg.key)}` }));
  }
});

async function flush() {
  if (!queue.length) return;
  const batch = queue.splice(0, 150);
  const s = await settings();
  if (!s.enabled) { queue = []; return; }
  const tabs = [...new Set(batch.map((x) => x.tab).filter((t) => t != null))];
  const out = await call("/api/capture", { jobs: batch.map((x) => x.job) });
  if (!out.ok) {
    session.error = out.error;
    chrome.action.setBadgeText({ text: "off" });
    chrome.action.setBadgeBackgroundColor({ color: "#cf222e" });
    queue = batch.concat(queue).slice(0, 1500);
    retryDelay = Math.min(30000, (retryDelay || 2500) * 2);
    for (const tab of tabs) {
      tell(tab, { ok: false, error: out.error, forget: batch.filter((x) => x.tab === tab).map((x) => x.job.id) });
    }
    clearTimeout(timer);
    timer = setTimeout(flush, retryDelay);
    return;
  }
  retryDelay = 0;
  session.error = "";
  session.sent += (out.added || 0) + (out.updated || 0);
  for (const a of out.alerts || []) {
    session.alerts += 1;
    if (s.notify) {
      chrome.notifications.create(a.url || String(Date.now()), {
        type: "basic", iconUrl: "icons/icon128.png", priority: 1,
        title: `${a.verdict} ${a.score} · ${a.title}`, message: a.company || "A strong match",
      });
    }
  }
  for (const x of batch) {
    if (x.tab != null) (perTab.get(x.tab) || perTab.set(x.tab, new Set()).get(x.tab)).add(x.job.id);
  }
  for (const tab of tabs) {
    const ids = new Set(batch.filter((x) => x.tab === tab).map((x) => `${x.job.source}:${x.job.id}`));
    tell(tab, { ok: true, count: (perTab.get(tab) || new Set()).size, marks: (out.marks || []).filter((m) => ids.has(m.key)) });
  }
  if (queue.length) timer = setTimeout(flush, 300);
}

function tell(tab, status) {
  chrome.tabs.sendMessage(tab, { type: "scanner-status", ...status }).catch(() => {});
  chrome.action.setBadgeText({ tabId: tab, text: status.ok ? (status.count ? String(status.count) : "") : "off" });
  chrome.action.setBadgeBackgroundColor({ tabId: tab, color: status.ok ? "#0f6b4f" : "#cf222e" });
}
chrome.tabs.onRemoved.addListener((tab) => perTab.delete(tab));
chrome.tabs.onUpdated.addListener((tab, change) => { if (change.status === "loading" && change.url) perTab.delete(tab); });

chrome.notifications.onClicked.addListener((id) => { if (id.startsWith("https://")) chrome.tabs.create({ url: id }); });

/* ---------- filling application forms (only when the person clicks Fill this application) ---------- */
const fillState = new Map(); // tabId -> { key, frames: frame ids with questions left }

async function fetchFile(path) {
  const s = await settings();
  try {
    const res = await fetch(`${s.server}${path}`, { headers: { "X-Scanner-Token": s.token } });
    if (!res.ok) return null;
    const bytes = new Uint8Array(await res.arrayBuffer());
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    const m = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get("Content-Disposition") || "");
    return { data: btoa(bin), name: m ? decodeURIComponent(m[1]) : "document.pdf" };
  } catch (_) { return null; }
}

function inFrames(tabId, frameIds, func, args = []) {
  const target = frameIds ? { tabId, frameIds } : { tabId, allFrames: true };
  return chrome.scripting.executeScript({ target, func, args }).catch(() => []);
}
const banner = (tabId, text) => inFrames(tabId, [0], (t) => window.__jobScannerBanner && window.__jobScannerBanner(t), [text]);

async function fillTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const data = await call("/api/capture/autofill", { url: tab.url });
  if (!data.ok) return data;
  if (data.job) {
    const key = encodeURIComponent(data.job.key);
    if (data.has_resume) data.resume_pdf = await fetchFile(`/api/capture/export?key=${key}&doc=resume&format=pdf`);
    if (data.letter) data.letter_pdf = await fetchFile(`/api/capture/export?key=${key}&doc=letter&format=pdf`);
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["fill.js"] });
  } catch (_) {
    return { ok: false, error: "Chrome doesn't allow filling this page." };
  }
  const results = await inFrames(tabId, null, (d) => (window.__jobScannerFill ? window.__jobScannerFill(d) : null), [data]);
  const out = { ok: true, job: data.job, filled: 0, attached: [], personal: [], questions: 0, need_access: [] };
  const frames = [];
  for (const r of results) {
    const x = r.result;
    if (!x) continue;
    out.filled += x.filled.length;
    out.attached.push(...x.attached);
    out.personal.push(...x.personal);
    out.questions += x.questions.length;
    if (x.questions.length) frames.push(r.frameId);
    for (const host of x.frames || []) {
      if (!(await chrome.permissions.contains({ origins: [`https://${host}/*`] }))) out.need_access.push(host);
    }
  }
  fillState.set(tabId, { key: data.job ? data.job.key : "", frames });
  const bits = [`Job Scanner filled ${out.filled} field${out.filled === 1 ? "" : "s"}`];
  if (out.attached.length) bits.push(`attached your ${out.attached.join(" and ").toLowerCase()}`);
  let text = bits.join(" and ") + ". Check everything before you submit: nothing has been sent.";
  if (out.personal.length) text += ` ${out.personal.length} personal question${out.personal.length === 1 ? " is" : "s are"} left for you.`;
  if (out.questions) text += ` ${out.questions} question${out.questions === 1 ? "" : "s"} still empty.`;
  banner(tabId, text);
  return out;
}

async function answerTab(tabId) {
  const st = fillState.get(tabId);
  if (!st || !st.frames.length) return { ok: false, error: "Fill the form first; there are no open questions." };
  if (!st.key) return { ok: false, error: "Job Scanner doesn't know which job this form is for. Open the posting with the extension on (or use Easy apply on it) first." };
  const asked = await inFrames(tabId, st.frames, () => (window.__jobScannerQuestions ? window.__jobScannerQuestions() : []));
  const questions = [...new Set(asked.flatMap((r) => r.result || []))].slice(0, 25);
  if (!questions.length) return { ok: false, error: "No open questions left." };
  banner(tabId, `Claude is drafting answers to ${questions.length} question${questions.length === 1 ? "" : "s"} from your résumés…`);
  const out = await call("/api/capture/answers", { key: st.key, questions });
  if (!out.ok) { banner(tabId, out.error); return out; }
  const done = await inFrames(tabId, st.frames, (items) => (window.__jobScannerAnswer ? window.__jobScannerAnswer(items) : 0), [out.answers]);
  const n = done.reduce((t, r) => t + (r.result || 0), 0);
  const blank = out.answers.filter((a) => !a.answer).length;
  banner(tabId, n ? `Claude drafted ${n} answer${n === 1 ? "" : "s"} (outlined in amber). Read each one before you submit.` +
    (blank ? ` ${blank} couldn't be answered from your résumés, so they're left for you.` : "")
    : `Your résumés don't show what ${questions.length === 1 ? "this question asks" : "these questions ask"}, so Claude left ${questions.length === 1 ? "it" : "them"} for you to answer.`);
  return { ok: true, answered: n, blank, answers: out.answers };
}

// Keep up to date: when the app's copy of the extension (after `git pull`) is newer than the one loaded, reload.
function newer(a, b) {
  const pa = String(a).split(".").map(Number), pb = String(b).split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}
async function checkForUpdate() {
  const out = await call("/api/capture/ping");
  const mine = chrome.runtime.getManifest().version;
  if (!out.ok || !out.extension_version || !newer(out.extension_version, mine)) return;
  const { reloadTried } = await chrome.storage.local.get({ reloadTried: "" });
  if (reloadTried === out.extension_version) return; // loaded from another folder; reloading won't help
  await chrome.storage.local.set({ reloadTried: out.extension_version });
  chrome.runtime.reload();
}
chrome.alarms.create("scanner-update", { periodInMinutes: 30 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "scanner-update") checkForUpdate(); });
chrome.runtime.onStartup.addListener(checkForUpdate);
