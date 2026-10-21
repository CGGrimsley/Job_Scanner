/* Job Scanner: background worker. Batches captured jobs to your Job Scanner app and relays the panel's requests. */
"use strict";

const DEFAULTS = { server: "http://127.0.0.1:8766", token: "", enabled: true, notify: true };
let queue = [];
let timer = null;
let retryDelay = 0;
const session = { sent: 0, alerts: 0, error: "", problems: {} };
const perTab = new Map(); // tabId -> Set of job ids the app has accepted from that page
const pendingAuto = new Map(); // tabId -> the job an automatic Claude read is waiting on for that tab

const settings = () => chrome.storage.local.get(DEFAULTS);

async function call(path, body) {
  const s = await settings();
  try {
    const res = await fetch(`${s.server}${path}`, body === undefined
      ? { headers: { "X-Scanner-Token": s.token } }
      : { method: "POST", headers: { "Content-Type": "application/json", "X-Scanner-Token": s.token }, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    return res.ok ? { ok: true, ...out } : { ...out, ok: false, error: out.error || `Job Scanner answered ${res.status}` };
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
      const job = { source: msg.source, id: msg.id };
      if (msg.auto && tab != null) {
        // a newer posting in this tab replaces the read still waiting for the old one
        const prev = pendingAuto.get(tab);
        if (prev && prev.id !== job.id) cancelRead(prev);
        pendingAuto.set(tab, job);
      }
      call("/api/capture/analyze", { ...job, auto: !!msg.auto, force: !!msg.force }).then((r) => {
        if (tab != null && pendingAuto.get(tab) === job) pendingAuto.delete(tab);
        reply(r);
      });
    });
    return true; // Claude takes a little while
  } else if (msg.type === "health") {
    const k = `${msg.source}:${msg.what}`;
    if (msg.ok) delete session.problems[k]; else session.problems[k] = { source: msg.source, what: msg.what, path: msg.path };
    call("/api/capture/health", { source: msg.source, what: msg.what, ok: !!msg.ok, path: msg.path });
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
function cancelRead(job) { call("/api/capture/cancel", job); }
function leftTab(tab) {
  const job = pendingAuto.get(tab);
  if (job) { pendingAuto.delete(tab); cancelRead(job); }
}
chrome.tabs.onRemoved.addListener((tab) => { perTab.delete(tab); leftTab(tab); });
chrome.tabs.onUpdated.addListener((tab, change) => { if (change.status === "loading" && change.url) { perTab.delete(tab); leftTab(tab); } });

chrome.notifications.onClicked.addListener(async (id) => {
  if (id.startsWith("https://")) chrome.tabs.create({ url: id });
  if (id === "follow-ups") chrome.tabs.create({ url: `${(await settings()).server}/#tracker` });
});

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
// Once a day at most: a reminder when applications are due a follow-up.
async function checkFollowUps() {
  const s = await settings();
  if (!s.notify) return;
  const out = await call("/api/capture/due");
  if (!out.ok || !out.count) return;
  const today = new Date().toISOString().slice(0, 10);
  const { dueNoticed } = await chrome.storage.local.get({ dueNoticed: "" });
  if (dueNoticed === today) return;
  await chrome.storage.local.set({ dueNoticed: today });
  chrome.notifications.create("follow-ups", {
    type: "basic", iconUrl: "icons/icon128.png", priority: 1,
    title: out.count === 1 ? "1 application is due a follow-up" : `${out.count} applications are due a follow-up`,
    message: out.jobs.map((j) => [j.title, j.company].filter(Boolean).join(" at ")).join("; ") || "See the Tracker in Job Scanner.",
  });
}
chrome.alarms.create("scanner-update", { periodInMinutes: 30 });
chrome.alarms.create("scanner-followups", { delayInMinutes: 1, periodInMinutes: 180 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "scanner-update") checkForUpdate();
  if (a.name === "scanner-followups") checkFollowUps();
});
chrome.runtime.onStartup.addListener(checkForUpdate);
