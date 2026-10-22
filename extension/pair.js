/* Job Scanner: one-click pairing. Runs only on the Job Scanner app itself (http://127.0.0.1 or localhost). It tells
   the app the extension is installed, and when you click "Connect the extension" on the app's Setup page, it saves
   the app's address and pairing token, so nothing needs copying. It reads nothing else from the page. */
"use strict";
(() => {
  if (!document.querySelector('meta[name="job-scanner-app"]')) return; // some other local page
  document.documentElement.dataset.jobScannerExtension = chrome.runtime.getManifest().version;
  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin || !e.data || e.data.type !== "job-scanner-pair") return;
    const token = String(e.data.token || "");
    if (!/^[\w-]{16,128}$/.test(token)) return;
    chrome.runtime.sendMessage({ type: "pair", server: location.origin, token }, (r) => {
      window.postMessage({ type: "job-scanner-paired", ok: !!(r && r.ok), error: (r && r.error) || "", jobs: r && r.jobs }, location.origin);
    });
  });
})();
