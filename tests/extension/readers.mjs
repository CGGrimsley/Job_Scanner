// Runs the extension's page reader (capture.js) against saved sample pages and prints what it read, as JSON.
// Used by tests/test_extension_readers.py; needs Node and Playwright (npm i -g playwright), else that test skips.
// When a site changes its pages, save a fresh copy into tests/fixtures/ and add it below.
import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { createRequire } from "module";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const root = path.resolve(here, "..", "..");
let playwright;
try { playwright = createRequire(import.meta.url)("playwright"); } catch (_) {
  playwright = createRequire(path.join(execSync("npm root -g").toString().trim(), "x.js"))("playwright");
}
const PAGES = [
  ["linkedin.html", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678"],
  ["linkedin-changed.html", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678", 10500], // long enough to warn
  ["linkedin-new.html", "https://www.linkedin.com/jobs/search-results/?currentJobId=4457298164&keywords=analyst"],
  ["indeed.html", "https://www.indeed.com/jobs?q=data"],
  ["ncworks.html", "https://www.ncworks.gov/vosnet/jobbanks/jobsearch.aspx"],
  ["greenhouse.html", "https://boards.greenhouse.io/acmehealth/jobs/4012345"],
];
const capture = fs.readFileSync(path.join(root, "extension", "capture.js"), "utf8");
const exe = process.env.PLAYWRIGHT_CHROMIUM || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
const browser = await playwright.chromium.launch(exe ? { executablePath: exe } : {});
const out = {};
for (const [file, url, wait] of PAGES) {
  const page = await browser.newPage();
  const html = fs.readFileSync(path.join(root, "tests", "fixtures", file), "utf8");
  await page.route("**/*", (r) => r.request().isNavigationRequest() ? r.fulfill({ contentType: "text/html", body: html }) : r.abort());
  // a stand-in for the extension APIs: records what the reader sends and answers nothing
  await page.addInitScript(() => {
    window.__sent = []; window.__listeners = [];
    window.chrome = { runtime: { sendMessage: (m, cb) => { window.__sent.push(m); }, onMessage: { addListener: (f) => window.__listeners.push(f) },
      getManifest: () => ({ version: "test" }) },
      storage: { local: { get: (d, cb) => cb(d) }, onChanged: { addListener() {} } } };
  });
  await page.goto(url);
  await page.addScriptTag({ content: capture });
  await page.waitForTimeout(wait || 1500);
  out[file] = await page.evaluate(async () => {
    const diag = await new Promise((ok) => window.__listeners[0]({ type: "diagnostics" }, {}, ok));
    const jobs = window.__sent.filter((m) => m.type === "capture").flatMap((m) => m.jobs);
    return { diag, jobs, health: window.__sent.filter((m) => m.type === "site-health") };
  });
  await page.close();
}
await browser.close();
console.log(JSON.stringify(out));
