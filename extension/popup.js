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
  const names = { linkedin: "LinkedIn", indeed: "Indeed", ncworks: "NCWorks", greenhouse: "Greenhouse", lever: "Lever", workday: "Workday" };
  const bad = Object.values(st.problems || {}).map((p) => `${names[p.source] || p.source} ${p.what === "posting" ? "postings" : "search results"}`);
  say($("problems"), bad.length ? `Can't read ${bad.join(" or ")}: the site may have changed its pages. On that page, click Copy diagnostics below and send it in.` : "");
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
