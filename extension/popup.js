"use strict";
const $ = (id) => document.getElementById(id);
const say = (el, text) => { el.hidden = !text; el.textContent = text || ""; };

chrome.storage.local.get({ server: "http://127.0.0.1:8766", enabled: true }, (s) => {
  $("open").href = s.server + "/";
  $("enabled").checked = s.enabled;
});
$("enabled").addEventListener("change", (e) => chrome.storage.local.set({ enabled: e.target.checked }));

chrome.runtime.sendMessage({ type: "status" }, (st) => {
  if (!st) return;
  $("sent").textContent = st.sent;
  $("alerts").textContent = st.alerts;
});
chrome.runtime.sendMessage({ type: "ping" }, (r) => {
  if (r && r.ok) {
    $("jobs").textContent = r.jobs;
    $("status").textContent = r.profile_ready ? "Connected." : "Connected. Fill in your Profile in the app for real scores.";
    $("status").className = "status ok";
  } else {
    $("status").textContent = (r && r.error) || "Not connected.";
    $("status").className = "status bad";
  }
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

$("scan").addEventListener("click", async () => {
  const tab = await activeTab();
  if (!tab || !/^https?:/.test(tab.url || "")) return say($("scanmsg"), "Open a job posting first.");
  try {
    // the content script is already there on the sites it knows; anywhere else this injects it once
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["capture.js"] });
    chrome.tabs.sendMessage(tab.id, { type: "scan-now" }, (r) => {
      if (chrome.runtime.lastError || !r) return say($("scanmsg"), "Sent. The panel in the page's corner shows the result.");
      say($("scanmsg"), r.posting ? "Posting sent. Its fit shows in the panel in the page's corner." : `Read ${r.cards} job cards on this page.`);
    });
  } catch (e) {
    say($("scanmsg"), "Chrome doesn't allow reading this page.");
  }
});

$("diag").addEventListener("click", async () => {
  const tab = await activeTab();
  chrome.tabs.sendMessage(tab.id, { type: "diagnostics" }, async (r) => {
    if (chrome.runtime.lastError || !r) return say($("diagmsg"), "Nothing to report: this page isn't one the extension reads.");
    const text = "Job Scanner diagnostics (public page data only)\n" + JSON.stringify(r, null, 2);
    try { await navigator.clipboard.writeText(text); say($("diagmsg"), "Copied. Paste it to Claude or into an issue."); }
    catch (_) { say($("diagmsg"), "Couldn't copy."); }
  });
});

// Filling an application form: the background worker does the work, so it carries on if this popup closes.
let needAccess = [];
async function fill() {
  const tab = await activeTab();
  if (!tab || !/^https:/.test(tab.url || "")) return say($("fillmsg"), "Open the application form first.");
  $("fill").disabled = true;
  say($("fillmsg"), "Filling…");
  chrome.runtime.sendMessage({ type: "fill-tab", tabId: tab.id }, (r) => {
    $("fill").disabled = false;
    if (!r || !r.ok) return say($("fillmsg"), (r && r.error) || "Couldn't fill this page.");
    const bits = [`Filled ${r.filled} field${r.filled === 1 ? "" : "s"}`];
    if (r.attached.length) bits.push(`attached your ${r.attached.join(" and ").toLowerCase()}`);
    let text = bits.join(", ") + (r.job ? ` for ${r.job.title}${r.job.company ? " at " + r.job.company : ""}.` : ". (No saved job matched this form, so only your details were used.)");
    if (r.personal.length) text += ` Left for you: ${r.personal.length} personal question${r.personal.length === 1 ? "" : "s"}.`;
    if (r.questions) text += ` ${r.questions} question${r.questions === 1 ? " is" : "s are"} still empty.`;
    text += " Check everything before you submit.";
    say($("fillmsg"), text);
    $("answer").hidden = !(r.questions && r.job);
    needAccess = r.need_access || [];
    $("allow").hidden = !needAccess.length;
    $("allow").textContent = `Allow filling forms from ${needAccess.join(", ")}`;
  });
}
$("fill").addEventListener("click", fill);
$("allow").addEventListener("click", async () => {
  // the form sits in a frame from another site (e.g. an embedded Greenhouse form): ask for just that site
  const ok = await chrome.permissions.request({ origins: needAccess.map((h) => `https://${h}/*`) }).catch(() => false);
  if (ok) { $("allow").hidden = true; fill(); } else say($("fillmsg"), "Without that, Job Scanner can't reach the form inside the page.");
});
$("answer").addEventListener("click", async () => {
  const tab = await activeTab();
  $("answer").disabled = true;
  $("answer").textContent = "Claude is writing…";
  chrome.runtime.sendMessage({ type: "answer-tab", tabId: tab.id }, (r) => {
    $("answer").disabled = false;
    $("answer").textContent = "Draft answers with Claude";
    if (!r || !r.ok) return say($("fillmsg"), (r && r.error) || "Couldn't draft answers.");
    say($("fillmsg"), r.answered ? `Drafted ${r.answered} answer${r.answered === 1 ? "" : "s"} (outlined in amber). Read each one before you submit.` +
      (r.blank ? ` ${r.blank} couldn't be answered from your résumés, so they're left for you.` : "")
      : "Your résumés don't show what the open questions ask, so they're left for you to answer.");
  });
});
