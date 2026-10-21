// The extension's page readers (extension/capture.js) against saved job pages in tests/fixtures/pages.
// When a site changes, save the new page there (Ctrl+S, "Webpage, HTML only"), add a case below, and fix the reader
// until it passes. Run with `npm test` after `npm install`.
"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const CAPTURE = fs.readFileSync(path.join(ROOT, "extension", "capture.js"), "utf8");
const BLOCK = /^(ADDRESS|ARTICLE|ASIDE|BLOCKQUOTE|BR|BUTTON|DD|DIV|DL|DT|FOOTER|FORM|H[1-6]|HEADER|HR|LI|MAIN|NAV|OL|P|PRE|SECTION|TABLE|TD|TH|TR|UL)$/;

// jsdom does no layout, so it has no innerText: approximate it with line breaks around block elements
function innerText(node) {
  let out = "";
  for (const n of node.childNodes) {
    if (n.nodeType === 3) out += n.nodeValue.replace(/\s+/g, " ");
    else if (n.nodeType === 1 && !/^(SCRIPT|STYLE|TEMPLATE)$/.test(n.tagName)) {
      const block = BLOCK.test(n.tagName);
      out += (block ? "\n" : "") + innerText(n) + (block ? "\n" : "");
    }
  }
  return out;
}

function open(file, url) {
  const dom = new JSDOM(fs.readFileSync(path.join(ROOT, "tests", "fixtures", "pages", file), "utf8"), { url, runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w.HTMLElement.prototype, "innerText", { get() { return innerText(this); } });
  const sent = [];
  let onMessage = null;
  w.chrome = {
    runtime: { sendMessage: (msg) => sent.push(msg), onMessage: { addListener: (f) => (onMessage = f) }, getManifest: () => ({ version: "test" }) },
    storage: { local: { get: (defaults, cb) => cb(defaults) }, onChanged: { addListener() {} } },
  };
  w.eval(CAPTURE);
  const ask = (type) => { let out; onMessage({ type }, null, (r) => (out = r)); return out; };
  return { w, sent, diagnostics: () => ask("diagnostics"), close: () => w.close() };
}
const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

test("LinkedIn search: cards and the open posting", () => {
  const page = open("linkedin-search.html", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=analyst");
  try {
    const d = page.diagnostics();
    assert.equal(d.site, "linkedin");
    assert.equal(d.cards_found, 3);
    const [first, second, third] = d.cards;
    assert.equal(first.id, "4012345678");
    assert.equal(first.title, "Data Analyst");
    assert.equal(first.company, "Acme Corp");
    assert.equal(first.location, "Raleigh, NC (Hybrid)");
    assert.equal(first.remote, "hybrid");
    assert.match(first.pay_text, /\$65K\/yr - \$80K\/yr/);
    assert.equal(first.easy_apply, true);
    assert.equal(second.title, "Senior Business Analyst");
    assert.equal(second.remote, "remote");
    assert.equal(third.title, undefined); // not rendered yet: skipped, not misread
    assert.equal(d.current.id, "4012345678");
    assert.equal(d.item.title, "Data Analyst");
    assert.equal(d.item.company, "Acme Corp");
    assert.equal(d.item.applicants, 100);
    assert.match(d.item.description, /3\+ years of experience with SQL/);
  } finally { page.close(); }
});

test("Indeed search: cards and the right pane", () => {
  const page = open("indeed-search.html", "https://www.indeed.com/jobs?q=analyst&l=Raleigh%2C+NC&vjk=0123456789abcdef");
  try {
    const d = page.diagnostics();
    assert.equal(d.site, "indeed");
    assert.equal(d.cards_found, 2);
    assert.equal(d.cards[0].title, "Operations Analyst");
    assert.equal(d.cards[0].company, "Initech");
    assert.equal(d.cards[0].location, "Durham, NC");
    assert.equal(d.cards[0].pay_text, "$22 - $26 an hour");
    assert.equal(d.cards[0].easy_apply, true);
    assert.equal(d.cards[1].remote, "remote");
    assert.equal(d.current.id, "0123456789abcdef");
    assert.equal(d.item.title, "Operations Analyst");
    assert.equal(d.item.job_type, "Full-time");
    assert.match(d.item.description, /two \(2\) years of experience/);
  } finally { page.close(); }
});

test("Greenhouse posting: read from its JobPosting data", () => {
  const page = open("greenhouse-posting.html", "https://boards.greenhouse.io/hooli/jobs/7654321");
  try {
    const d = page.diagnostics();
    assert.equal(d.site, "greenhouse");
    assert.equal(d.json_ld, true);
    assert.equal(d.current.id, "7654321");
    assert.equal(d.item.title, "Security Analyst");
    assert.equal(d.item.company, "Hooli");
    assert.equal(d.item.location, "Arlington, VA");
    assert.equal(d.item.pay_min, 95000);
    assert.equal(d.item.pay_max, 120000);
    assert.match(d.item.description, /TS\/SCI/);
  } finally { page.close(); }
});

test("a posting the reader can't read is reported, not skipped quietly", async () => {
  const page = open("linkedin-changed.html", "https://www.linkedin.com/jobs/view/4012345678/");
  try {
    assert.equal(page.diagnostics().item, null);
    let now = Date.now();
    page.w.Date.now = () => now;
    page.w.dispatchEvent(new page.w.Event("scroll"));
    await wait(800); // first look: starts the clock
    assert.equal(page.sent.filter((m) => m.type === "health").length, 0);
    now += 9000;
    page.w.dispatchEvent(new page.w.Event("scroll"));
    await wait(800);
    const reports = JSON.parse(JSON.stringify(page.sent.filter((m) => m.type === "health"))); // objects from the page's realm
    assert.deepEqual(reports, [{ type: "health", source: "linkedin", what: "posting", ok: false, path: "/jobs/view/4012345678/" }]);
  } finally { page.close(); }
});

test("a posting that reads fine is reported as fine", async () => {
  const page = open("linkedin-search.html", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678");
  try {
    page.w.dispatchEvent(new page.w.Event("scroll"));
    await wait(800);
    const reports = page.sent.filter((m) => m.type === "health");
    assert.ok(reports.some((m) => m.what === "posting" && m.ok));
  } finally { page.close(); }
});
