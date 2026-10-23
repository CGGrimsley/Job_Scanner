"use strict";
const f = document.getElementById("f");
const msg = document.getElementById("msg");
const DEFAULTS = { server: "http://127.0.0.1:8766", token: "", notify: true, indicator: true, dimSkip: false };
chrome.storage.local.get(DEFAULTS, (s) => {
  f.server.value = s.server;
  f.token.value = s.token;
  f.notify.checked = s.notify;
  f.indicator.checked = s.indicator;
  f.dimSkip.checked = s.dimSkip;
});
function normalise(raw) {
  let server = (raw.trim() || DEFAULTS.server).replace(/\/+$/, "");
  // no scheme typed: plain http for this computer and home-network addresses (an IP, a .lan/.local/.home.arpa name or
  // a bare hostname like "homelab"), https for anything else
  const host = server.split(/[/:]/)[0];
  const home = /^[\d.]+$|^\[|^localhost$|\.(lan|local|home|internal|home\.arpa)$|^[^.]+$/i.test(host);
  if (!/^https?:\/\//i.test(server)) server = (home ? "http://" : "https://") + server;
  return server;
}
f.addEventListener("submit", (e) => {
  e.preventDefault();
  const server = normalise(f.server.value);
  let url;
  try { url = new URL(server); } catch (_) {
    msg.textContent = "That address doesn't look right.";
    msg.className = "status bad";
    return;
  }
  f.server.value = server;
  const local = url.hostname === "127.0.0.1" || url.hostname === "localhost";
  // asked straight away, while the click still counts as the user's: Chrome only shows the prompt then
  const granted = local ? Promise.resolve(true) : chrome.permissions.request({ origins: [`${url.protocol}//${url.hostname}/*`] });
  granted.then((ok) => {
    if (!ok) { msg.textContent = "Chrome needs permission to reach that address."; msg.className = "status bad"; return; }
    chrome.storage.local.set({ server, token: f.token.value.trim(), notify: f.notify.checked, indicator: f.indicator.checked, dimSkip: f.dimSkip.checked }, () => {
      msg.textContent = "Testing…";
      chrome.runtime.sendMessage({ type: "ping" }, (r) => {
        msg.textContent = r && r.ok ? `Connected. ${r.jobs} jobs in the app.` : (r && r.error) || "No answer.";
        msg.className = "status " + (r && r.ok ? "ok" : "bad");
      });
    });
  });
});
