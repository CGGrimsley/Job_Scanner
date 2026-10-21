/* Job Scanner: reads the job cards and postings on the page you're looking at and sends them to your Job Scanner
   app, then stamps each card with how well it fits you. It's passive: it only reads what you scroll past or open,
   and never clicks, scrolls, applies or fetches anything by itself. */
(() => {
  "use strict";
  if (window.__jobScanner) { window.__jobScanner.scanNow(); return; }

  const host = location.hostname.replace(/^www\./, "");

  /* ---------- helpers ---------- */
  const clean = (s, n = 400) => String(s || "").replace(/[ \t ]+/g, " ").replace(/\n{3,}/g, "\n\n").trim().slice(0, n);
  const one = (root, sel) => { try { return (root || document).querySelector(sel); } catch (_) { return null; } };
  const textOf = (root, sel) => { const el = sel ? one(root, sel) : root; return el ? clean(el.innerText || el.textContent) : ""; };
  const lines = (el) => [...new Set(String((el && el.innerText) || "").split(/[\n\t]/).map((l) => clean(l, 200)).filter(Boolean))];
  const hash = (s) => { let h = 5381; for (const c of String(s)) h = ((h * 33) ^ c.charCodeAt(0)) >>> 0; return h.toString(36); };
  const param = (name, url = location.href) => { try { return new URL(url, location.href).searchParams.get(name); } catch (_) { return null; } };
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };

  const AMT = String.raw`\$\s?\d[\d,]*(?:\.\d+)?\s?[kK]?(?:\s*(?:\/|an?|per)\s*(?:hour|hr|year|yr|month|mo|week|wk|annum))?`;
  const PAY = new RegExp(`${AMT}(?:\\s?(?:-|–|to)\\s?\\$?${AMT.slice(2)})?`, "i"); // "$65K/yr - $80K/yr", "$18 - 20 an hour"
  const payText = (arr) => { for (const l of arr) { const m = l.match(PAY); if (m) return clean(m[0], 120); } return ""; };
  const POSTED = /(\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago|just posted|posted today|today|yesterday|reposted[^·\n]*ago)/i;
  const postedText = (arr) => { for (const l of arr) { const m = l.match(POSTED); if (m) return clean(m[0], 60); } return ""; };
  function applicants(text) {
    const m = String(text).match(/(?:over\s+)?(\d[\d,]*)\+?\s+(?:applicants|people clicked apply|candidates)/i);
    return m ? parseInt(m[1].replace(/,/g, ""), 10) : undefined;
  }
  function remoteOf(text) {
    const t = String(text).toLowerCase();
    if (/\bhybrid\b/.test(t)) return "hybrid";
    if (/\bremote\b|work from home/.test(t)) return "remote";
    if (/\bon-?site\b|in[- ]person/.test(t)) return "onsite";
    return undefined;
  }
  const JOB_TYPE = /\b(full[- ]time|part[- ]time|contract(?:or)?|temporary|temp[- ]to[- ]hire|internship|seasonal|per diem)\b/i;
  const jobType = (text) => { const m = String(text).match(JOB_TYPE); return m ? m[1] : ""; };

  // Most career sites embed the posting as schema.org JobPosting data for search engines: the most reliable read.
  function jsonLdJob() {
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      let data;
      try { data = JSON.parse(s.textContent); } catch (_) { continue; }
      const stack = [data];
      while (stack.length) {
        const x = stack.pop();
        if (!x || typeof x !== "object") continue;
        if (Array.isArray(x)) { stack.push(...x); continue; }
        const type = [].concat(x["@type"] || []);
        if (type.includes("JobPosting")) return x;
        if (x["@graph"]) stack.push(x["@graph"]);
      }
    }
    return null;
  }
  function htmlText(html) {
    const d = document.createElement("div");
    d.innerHTML = String(html || "").replace(/<(br|\/p|\/li|\/h\d|\/div)[^>]*>/gi, "$&\n");
    return clean(d.textContent, 30000);
  }
  function fromJsonLd(j) {
    const org = j.hiringOrganization || {};
    const locs = [].concat(j.jobLocation || []).map((l) => {
      const a = (l && l.address) || {};
      return [a.addressLocality, a.addressRegion].filter(Boolean).join(", ");
    }).filter(Boolean);
    const row = {
      title: clean(j.title, 300), company: clean(typeof org === "string" ? org : org.name, 200),
      location: locs.slice(0, 3).join("; "), description: htmlText(j.description),
      job_type: clean([].concat(j.employmentType || []).join(", "), 100), posted_text: clean(j.datePosted, 40),
    };
    if (/TELECOMMUTE/i.test(j.jobLocationType || "")) row.remote = "remote";
    const sal = j.baseSalary && (j.baseSalary.value || j.baseSalary);
    if (sal && (sal.minValue || sal.maxValue || sal.value)) {
      const unit = String(sal.unitText || j.baseSalary.unitText || "YEAR").toUpperCase();
      const mult = { HOUR: 2080, DAY: 260, WEEK: 52, MONTH: 12, YEAR: 1 }[unit] || 1;
      const lo = +(sal.minValue || sal.value), hi = +(sal.maxValue || sal.value || sal.minValue);
      if (lo) row.pay_min = Math.round(lo * mult);
      if (hi) row.pay_max = Math.round(hi * mult);
      row.pay_text = `$${lo.toLocaleString()}${hi && hi !== lo ? " - $" + hi.toLocaleString() : ""} / ${unit.toLowerCase()}`;
    }
    if (j.validThrough && Date.parse(j.validThrough) < Date.now()) row.closed = true;
    return row;
  }
  // the longest description-like block on the page, for sites with no structured data
  function biggestDescription() {
    let best = "";
    for (const el of document.querySelectorAll('[id*="escription" i], [class*="escription" i], [id*="jobdesc" i], [class*="job-body" i], article, main')) {
      const t = clean(el.innerText, 30000);
      if (t.length > best.length) best = t;
    }
    return best.length > 200 ? best : clean(document.body.innerText, 15000);
  }

  /* ---------- the sites ---------- */
  const SITES = [
    {
      source: "linkedin", host: /(^|\.)linkedin\.com$/,
      cards() {
        const seen = new Map();
        for (const el of document.querySelectorAll("[data-occludable-job-id], [data-job-id]")) {
          const id = el.getAttribute("data-occludable-job-id") || el.getAttribute("data-job-id");
          if (!/^\d{6,}$/.test(id || "") || seen.has(id)) continue;
          if (el.closest(".jobs-search__job-details, .jobs-details, .job-view-layout")) continue;
          seen.set(id, el.closest("li") || el);
        }
        return [...seen].map(([id, el]) => ({ id, el, url: `https://www.linkedin.com/jobs/view/${id}/` }));
      },
      card(el) {
        const ls = lines(el);
        if (ls.length < 2) return null; // not rendered yet (LinkedIn fills cards in as they scroll into view)
        const title = textOf(el, ".job-card-list__title--link strong, .job-card-list__title strong, a.job-card-container__link strong, .artdeco-entity-lockup__title")
          .replace(/\s+with verification$/i, "") || ls[0];
        const company = textOf(el, ".artdeco-entity-lockup__subtitle, .job-card-container__primary-description, .job-card-container__company-name") || ls[1];
        const meta = [...el.querySelectorAll(".job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption li, .job-card-container__metadata-item")]
          .map((x) => clean(x.innerText, 120)).filter(Boolean);
        const location = meta.find((m) => !PAY.test(m)) || ls.find((l) => /,\s?[A-Z]{2}\b|\bremote\b|united states/i.test(l)) || "";
        const all = ls.join("\n");
        return { title, company, location, pay_text: payText(meta.concat(ls)), posted_text: postedText(ls), remote: remoteOf(location),
          easy_apply: /easy apply/i.test(all), applied_on_site: /(^|\n)applied\b/i.test(all),
          tags: ls.filter((l) => /promoted|actively (reviewing|recruiting)|easy apply|be an early applicant|in your network/i.test(l)).slice(0, 5) };
      },
      current() {
        const id = param("currentJobId") || (location.pathname.match(/\/jobs\/view\/(?:[^/]*-)?(\d{6,})/) || [])[1];
        if (!id) return null;
        const pane = one(document, ".jobs-search__job-details--container, .jobs-details, .job-view-layout, .scaffold-layout__detail, main") || document.body;
        const link = one(pane, '.job-details-jobs-unified-top-card__job-title a[href*="/jobs/view/"], .jobs-unified-top-card__job-title a[href*="/jobs/view/"]');
        if (link && !link.href.includes(id)) return null; // the pane hasn't caught up with the URL yet
        return { id, root: pane, url: `https://www.linkedin.com/jobs/view/${id}/` };
      },
      item(root) {
        const description = textOf(root, "#job-details, .jobs-description__content, .jobs-description-content__text, .jobs-box__html-content, .show-more-less-html__markup, .description__text");
        if (description.length < 80) return null;
        const title = textOf(root, ".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, .top-card-layout__title, h1");
        const company = textOf(root, ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, .topcard__org-name-link");
        const top = textOf(root, ".job-details-jobs-unified-top-card__tertiary-description-container, .job-details-jobs-unified-top-card__primary-description-container, .jobs-unified-top-card__primary-description, .topcard__flavor-row", 400);
        const parts = top.split(/\s*·\s*/).filter(Boolean);
        const pills = [...root.querySelectorAll(".job-details-fit-level-preferences button, .job-details-preferences-and-skills, .jobs-unified-top-card__job-insight, .job-details-jobs-unified-top-card__job-insight")]
          .map((x) => clean(x.innerText, 120)).filter(Boolean);
        const head = [top, ...pills].join("\n");
        return { title, company, location: parts[0] || "", posted_text: postedText(parts), applicants: applicants(head),
          pay_text: payText(pills.concat(parts)), remote: remoteOf(pills.join(" ")) || remoteOf(parts[0] || ""),
          job_type: jobType(pills.join(" ")), description, tags: pills.slice(0, 8),
          easy_apply: !!one(root, ".jobs-apply-button--top-card, .jobs-apply-button") && /easy apply/i.test(textOf(root, ".jobs-apply-button--top-card, .jobs-apply-button")),
          applied_on_site: /\bapplied\s+\d+\s+\w+\s+ago\b/i.test(textOf(root, ".jobs-s-apply, .artdeco-inline-feedback, .post-apply-timeline")),
          closed: /no longer accepting applications/i.test(textOf(root, ".jobs-details-top-card__apply-error, .artdeco-inline-feedback, .jobs-s-apply")) };
      },
    },
    {
      source: "indeed", host: /(^|\.)indeed\.com$/,
      cards() {
        const seen = new Map();
        for (const el of document.querySelectorAll("[data-jk]")) {
          const id = el.getAttribute("data-jk");
          if (!/^[0-9a-f]{10,20}$/i.test(id || "") || seen.has(id)) continue;
          const card = el.closest(".job_seen_beacon, .cardOutline, .result, li") || el;
          if (card.closest("#jobsearch-ViewjobPaneWrapper, .jobsearch-RightPane")) continue;
          seen.set(id, card);
        }
        return [...seen].map(([id, el]) => ({ id, el, url: `https://www.indeed.com/viewjob?jk=${id}` }));
      },
      card(el) {
        const ls = lines(el);
        const title = clean((one(el, "h2.jobTitle span[title]") || {}).title || textOf(el, "h2.jobTitle, .jobTitle, a[data-jk]")).replace(/^new\s+/i, "");
        if (!title) return null;
        const location = textOf(el, '[data-testid="text-location"], .companyLocation');
        const snippets = [...el.querySelectorAll('[data-testid="attribute_snippet_testid"], .salary-snippet-container, .estimated-salary, .metadata')]
          .map((x) => clean(x.innerText, 120)).filter(Boolean);
        const all = ls.join("\n");
        return { title, company: textOf(el, '[data-testid="company-name"], .companyName'), location,
          pay_text: payText(snippets.concat(ls)), job_type: jobType(snippets.join(" ")), posted_text: postedText(ls),
          remote: remoteOf(location), easy_apply: /easily apply/i.test(all), applied_on_site: /(^|\n)applied\b/i.test(all),
          tags: snippets.filter((s) => !PAY.test(s)).slice(0, 6) };
      },
      current() {
        const id = param("vjk") || param("jk");
        if (!id || !/^[0-9a-f]{10,20}$/i.test(id)) return null;
        const root = one(document, "#jobsearch-ViewjobPaneWrapper, .jobsearch-RightPane, .jobsearch-ViewJobLayout, main") || document.body;
        return { id, root, url: `https://www.indeed.com/viewjob?jk=${id}` };
      },
      item(root) {
        const description = textOf(root, "#jobDescriptionText");
        if (description.length < 80) return null;
        const info = textOf(root, '#salaryInfoAndJobType, [data-testid="jobsearch-OtherJobDetailsContainer"], #jobDetailsSection');
        const location = textOf(root, '[data-testid="inlineHeader-companyLocation"], [data-testid="job-location"], [data-testid="jobsearch-JobInfoHeader-companyLocation"], #jobLocationText');
        return { title: textOf(root, '[data-testid="jobsearch-JobInfoHeader-title"], .jobsearch-JobInfoHeader-title, h1').replace(/\s*-\s*job post$/i, ""),
          company: textOf(root, '[data-testid="inlineHeader-companyName"], [data-company-name="true"], .jobsearch-CompanyInfoContainer a'),
          location, pay_text: payText(info.split("\n")), job_type: jobType(info), remote: remoteOf(location + " " + info),
          description, tags: info.split("\n").filter((l) => l && !PAY.test(l)).slice(0, 6),
          closed: /this job has expired|no longer available/i.test(textOf(root, ".jobsearch-JobInfoHeader-expiredHeader, [data-testid='expired-job-message']")) };
      },
    },
    {
      // NCWorks (Geographic Solutions' Virtual OneStop). Job links carry a jobid (or an encrypted enc) parameter.
      source: "ncworks", host: /(^|\.)ncworks\.gov$/,
      idOf(href) {
        const jid = param("jobid", href) || param("JobID", href) || param("jobId", href) || param("id", href);
        if (jid && /^[\w-]{3,40}$/.test(jid)) return jid;
        const enc = param("enc", href);
        return enc ? "e" + hash(enc) : null;
      },
      isDetail(href) { return /job.?detail|jobid=|jobs?\/\d{4,}/i.test(href); },
      cards() {
        const seen = new Map();
        for (const a of document.querySelectorAll("a[href]")) {
          if (!this.isDetail(a.href) || a.closest("nav, header, footer")) continue;
          const id = this.idOf(a.href);
          if (!id || seen.has(id) || clean(a.innerText).length < 3) continue;
          let card = a.closest("tr, li, .card, [class*='result' i], [class*='job-item' i]") || a.parentElement;
          if (clean(card.innerText).length > 1500) card = a.parentElement;
          seen.set(id, { el: card, url: a.href, title: clean(a.innerText, 300) });
        }
        return [...seen].map(([id, x]) => ({ id, el: x.el, url: x.url, title: x.title }));
      },
      card(el, c) {
        const ls = lines(el).filter((l) => l !== c.title);
        const location = ls.find((l) => /,\s?(NC|North Carolina)\b|,\s?[A-Z]{2}\b/.test(l)) || "";
        return { title: c.title, company: ls.find((l) => l !== location && !PAY.test(l) && !/\d{1,2}\/\d{1,2}\/\d{2,4}/.test(l) && l.length < 100) || "",
          location, pay_text: payText(ls), job_type: jobType(ls.join(" ")), remote: remoteOf(ls.join(" ")),
          posted_text: (ls.join(" ").match(/\d{1,2}\/\d{1,2}\/\d{4}/) || [""])[0] };
      },
      current() {
        if (!this.isDetail(location.href)) return null;
        const id = this.idOf(location.href) || "u" + hash(location.pathname + location.search);
        return { id, root: document.body, url: location.href };
      },
      item() {
        const j = jsonLdJob();
        if (j) return fromJsonLd(j);
        const description = biggestDescription();
        const head = clean((one(document, "h1, h2") || {}).innerText, 300);
        return { title: head, description, pay_text: payText(description.split("\n").slice(0, 60)), job_type: jobType(description),
          remote: remoteOf(description.slice(0, 2000)) };
      },
    },
    // Company career pages that most "Apply" buttons lead to: these always carry JobPosting data.
    ...[["greenhouse", /(^|\.)greenhouse\.io$/, /\/jobs\/(\d{4,})/], ["lever", /(^|\.)lever\.co$/, /\/([0-9a-f-]{36})/],
        ["workday", /(^|\.)myworkdayjobs\.com$/, /\/job\/.*?_([A-Za-z0-9-]{3,40})(?:[/?#]|$)/]].map(([source, re, idRe]) => ({
      source, host: re, cards: () => [], card: () => null,
      current() {
        const m = location.pathname.match(idRe);
        return m ? { id: m[1], root: document.body, url: location.origin + location.pathname } : null;
      },
      item() {
        const j = jsonLdJob();
        if (j) return fromJsonLd(j);
        const description = textOf(document, '[data-automation-id="jobPostingDescription"], #content, .posting-page, .job__description', 30000);
        if (description.length < 80) return null;
        return { title: textOf(document, '[data-automation-id="jobPostingHeader"], h1, .posting-headline h2'), description };
      },
    })),
  ];
  // Any other site: only when you click "Scan this page" in the popup, which injects this script.
  const GENERIC = {
    source: "web", host: /./, cards: () => [], card: () => null,
    current() { return { id: hash(location.origin + location.pathname), root: document.body, url: location.origin + location.pathname }; },
    item() {
      const j = jsonLdJob();
      const sel = clean(String(getSelection()), 30000);
      const row = j ? fromJsonLd(j) : { title: clean(document.title, 300), description: sel.length > 200 ? sel : biggestDescription() };
      row.pay_text = row.pay_text || payText(row.description.split("\n").slice(0, 80));
      return row;
    },
  };
  const site = SITES.find((s) => s.host.test(host)) || GENERIC;

  /* ---------- talking to the extension ---------- */
  const send = (msg, cb) => { try { chrome.runtime.sendMessage(msg, cb); } catch (_) { /* extension reloaded */ } };
  let enabled = true, dimSkip = false;
  const sent = new Map(); // id -> signature of what was last sent, so unchanged cards aren't re-sent
  const marks = new Map(); // id -> the app's verdict

  function post(rows) {
    const fresh = rows.filter((r) => {
      const sig = hash(JSON.stringify(r));
      if (sent.get(r.id) === sig) return false;
      sent.set(r.id, sig);
      return true;
    });
    if (fresh.length) send({ type: "capture", jobs: fresh });
  }

  function scanCards() {
    const rows = [];
    for (const c of site.cards()) {
      if (!visible(c.el)) continue;
      let row = null;
      try { row = site.card(c.el, c); } catch (_) { row = null; }
      if (!row || !row.title) continue;
      rows.push({ source: site.source, id: c.id, kind: "card", url: c.url, ...row });
    }
    if (rows.length) post(rows);
    applyStamps();
  }

  let currentId = null, analysisAsked = new Set();
  function scanItem(force = false) {
    const cur = site.current();
    if (!cur) { if (currentId) { currentId = null; panel.job(null); } return; }
    let row = null;
    try { row = site.item(cur.root); } catch (_) { row = null; }
    if (!row || (!row.description && !force)) return;
    for (const k of Object.keys(row)) if (row[k] === undefined || row[k] === "") delete row[k];
    const changed = currentId !== cur.id;
    currentId = cur.id;
    post([{ source: site.source, id: cur.id, kind: "item", url: cur.url, ...row }]);
    if (changed) panel.job({ source: site.source, id: cur.id, title: row.title });
  }

  let timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (enabled) { scanCards(); scanItem(); } }, 700);
  }

  /* ---------- stamps on the cards ---------- */
  const COLORS = { Apply: ["#0f6b4f", "#e6f4ee"], Consider: ["#8a5a00", "#fdf3df"], Skip: ["#5f6368", "#f1f3f4"] };
  const STATUS = { saved: "Saved", applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn" };
  function stamp(mark) {
    const el = document.createElement("div");
    el.dataset.jobScanner = mark.id;
    el.style.cssText = "position:absolute;top:6px;right:6px;z-index:2;pointer-events:none;";
    const root = el.attachShadow({ mode: "closed" });
    const [ink, bg] = COLORS[mark.verdict] || COLORS.Skip;
    const label = STATUS[mark.status] ? `${STATUS[mark.status]} · ${mark.score}` : `${mark.by === "ai" ? "✦ " : ""}${mark.verdict} ${mark.score}`;
    root.innerHTML = `<span style="display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid ${ink};
      background:${bg};color:${ink};font:600 11px/1.3 system-ui,-apple-system,'Segoe UI',sans-serif;white-space:nowrap;
      box-shadow:0 1px 2px rgba(0,0,0,.12)"></span>`;
    root.firstElementChild.textContent = label;
    return el;
  }
  function applyStamps() {
    if (!marks.size) return;
    for (const c of site.cards()) {
      const m = marks.get(c.id);
      const old = c.el.querySelector(":scope > [data-job-scanner]");
      if (!m) { if (old) old.remove(); continue; }
      const sig = `${m.verdict}${m.score}${m.status}${m.by}`;
      if (!old || old.dataset.sig !== sig) {
        if (old) old.remove();
        if (getComputedStyle(c.el).position === "static") c.el.style.position = "relative";
        const s = stamp(m);
        s.dataset.sig = sig;
        c.el.appendChild(s);
      }
      c.el.style.opacity = dimSkip && m.verdict === "Skip" && !m.status ? "0.45" : "";
    }
  }

  /* ---------- the corner panel ---------- */
  const panel = (() => {
    const box = document.createElement("div");
    box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    const root = box.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
      .tag { display:flex; align-items:center; gap:8px; padding:7px 12px; border-radius:999px; cursor:pointer; user-select:none;
        background:#fff; color:#1f2328; border:1px solid #d0d7de; box-shadow:0 2px 8px rgba(0,0,0,.15); font:600 12px/1.2 inherit; }
      .dot { width:8px; height:8px; border-radius:50%; background:#8c959f; flex:none; }
      .ok .dot { background:#1a7f5a; } .bad .dot { background:#cf222e; }
      .card { display:none; width:340px; max-height:70vh; overflow:auto; margin-bottom:8px; padding:14px 16px; border-radius:12px;
        background:#fff; color:#1f2328; border:1px solid #d0d7de; box-shadow:0 8px 24px rgba(0,0,0,.18); font-size:13px; line-height:1.45; }
      .open .card { display:block; }
      h3 { margin:0 0 2px; font-size:14px; } .sub { color:#57606a; margin:0 0 10px; font-size:12px; }
      .score { display:inline-block; padding:2px 9px; border-radius:999px; font-weight:700; font-size:12px; margin-right:6px; }
      .Apply { background:#e6f4ee; color:#0f6b4f; } .Consider { background:#fdf3df; color:#8a5a00; } .Skip { background:#f1f3f4; color:#5f6368; }
      h4 { margin:12px 0 4px; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:#57606a; }
      ul { margin:0; padding-left:18px; } li { margin:2px 0; }
      .row { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
      button, a.btn { font:600 12px/1 inherit; padding:7px 10px; border-radius:8px; border:1px solid #d0d7de; background:#f6f8fa;
        color:#1f2328; cursor:pointer; text-decoration:none; }
      button.primary { background:#0f6b4f; border-color:#0f6b4f; color:#fff; }
      button:disabled { opacity:.6; cursor:default; }
      .note { color:#57606a; font-size:12px; margin-top:8px; }
      textarea.letter { width:100%; min-height:220px; margin-top:4px; padding:8px; border:1px solid #d0d7de; border-radius:8px; font:13px/1.45 inherit; resize:vertical; }
    </style>
    <div class="wrap"><div class="card"></div><div class="tag"><span class="dot"></span><span class="txt">Job Scanner · watching</span></div></div>`;
    const wrap = root.querySelector(".wrap"), tag = root.querySelector(".tag"), txt = root.querySelector(".txt"), card = root.querySelector(".card");
    let shown = false, showTag = true, job = null, data = null, busy = false, note = "", letter = "";
    tag.addEventListener("click", () => { wrap.classList.toggle("open"); if (wrap.classList.contains("open")) refresh(); });

    function mount() { if (!shown && showTag && document.body) { document.body.appendChild(box); shown = true; } }
    function status(state, text) {
      mount();
      tag.classList.remove("ok", "bad");
      if (state) tag.classList.add(state);
      txt.textContent = `Job Scanner · ${text}`;
    }
    const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const list = (title, items, fn = (x) => x) => items && items.length ? `<h4>${title}</h4><ul>${items.slice(0, 5).map((x) => `<li>${esc(fn(x))}</li>`).join("")}</ul>` : "";
    function render() {
      if (!job) { card.innerHTML = `<p class="sub">Open a job posting and its fit shows here.</p>`; return; }
      if (!data) { card.innerHTML = `<h3>${esc(job.title || "This job")}</h3><p class="sub">Reading the posting…</p>`; return; }
      const j = data.job, m = data.mark, ai = j.ai, r = j.rules || {};
      card.innerHTML = `<h3>${esc(j.title)}</h3><p class="sub">${esc([j.company, j.location].filter(Boolean).join(" · "))}</p>
        <span class="score ${m.verdict}">${m.verdict} ${m.score}</span><span class="sub">${m.by === "ai" ? `Claude's assessment${ai.confidence ? ` · ${ai.confidence} confidence` : ""}` : "Match to your preferences, not your chances"}</span>
        ${ai ? `<p>${esc(ai.summary)}</p>${ai.interview_odds ? `<p><b>Realistic odds:</b> ${esc(ai.interview_odds)}</p>` : ""}${list("Strengths", ai.strengths, (x) => x.requirement + ": " + x.evidence)}
          ${list("Gaps", ai.gaps, (x) => `${x.requirement} (${x.severity}). ${x.how_to_address}`)}
          ${list("Red flags", ai.red_flags)}${ai.best_resume ? `<h4>Résumé to send</h4><p>${esc(ai.best_resume)}</p>` : ""}${list("Conflicts with what you want", ai.preference_conflicts)}${list("Résumé tips", ai.resume_tips)}`
          : `${list("Good", r.reasons)}${list("Watch out", r.cautions)}`}
        <div class="row"><button class="primary" data-act="easy" ${busy ? "disabled" : ""}>${busy === "easy" ? "Writing your résumé, letter and answers…" : j.packet ? "Easy apply again" : "Easy apply"}</button></div>
        <div class="row">
          <button data-act="analyze" ${busy ? "disabled" : ""}>${busy === true ? "Claude is reading…" : ai ? "Ask Claude again" : "Ask Claude"}</button>
          <button data-act="saved">${j.status === "saved" ? "Saved ✓" : "Save"}</button>
          <button data-act="applied">${j.status === "applied" ? "Applied ✓" : "I applied"}</button>
          <button data-act="letter" ${busy || letter === null ? "disabled" : ""}>${letter === null ? "Writing…" : "Cover letter"}</button>
          <button data-act="app">Open in app</button>
        </div>${note ? `<p class="note">${esc(note)}</p>` : ""}
        ${letter ? `<h4>Cover letter</h4><textarea class="letter" readonly></textarea><div class="row"><button data-act="copy">Copy letter</button></div>` : ""}`;
      if (letter) card.querySelector(".letter").value = letter;
      card.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => act(b.dataset.act)));
    }
    function refresh() {
      if (!job) return render();
      send({ type: "get-job", source: job.source, id: job.id }, (r) => {
        if (r && r.job) { data = r; marks.set(job.id, r.mark); tagFor(r.mark); }
        render();
      });
    }
    function tagFor(m) { if (m && job && m.id === job.id) status("ok", `${m.by === "ai" ? "✦ " : ""}${m.verdict} ${m.score}`); }
    function analyze(auto) {
      if (!job || busy) return;
      busy = true; note = ""; render();
      if (!auto) status("ok", "asking Claude…");
      send({ type: "analyze", source: job.source, id: job.id, auto, force: !auto && !!(data && data.job.ai) }, (r) => {
        busy = false;
        if (r && r.job) { data = { job: r.job, mark: r.mark }; marks.set(job.id, r.mark); tagFor(r.mark); applyStamps(); }
        else if (r && r.mark) { tagFor(r.mark); if (!auto) note = r.skipped || ""; else note = r.skipped || ""; }
        else note = (r && r.error) || "Claude couldn't be reached.";
        if (r && r.skipped && !data) refresh(); else render();
      });
    }
    function act(a) {
      if (a === "analyze") return analyze(false);
      if (a === "easy") {
        if (busy) return;
        busy = "easy"; note = ""; render();
        status("ok", "Easy apply: Claude is writing…");
        send({ type: "easy-apply", source: job.source, id: job.id }, (r) => {
          busy = false;
          if (r && r.job) {
            data = { job: r.job, mark: r.mark }; marks.set(job.id, r.mark); tagFor(r.mark); applyStamps();
            const failed = Object.keys(r.errors || {});
            note = "Your tailored résumé, cover letter and answers are ready in the app (Open in app), and the job is saved to your tracker. " +
              "On the application form, click the Job Scanner icon and Fill this application." + (failed.length ? ` Not done: ${failed.join(", ")}.` : "");
          } else note = (r && r.error) || "Claude couldn't be reached.";
          render();
        });
        return;
      }
      if (a === "app") return send({ type: "open-app", key: `${job.source}:${job.id}` });
      if (a === "copy") { navigator.clipboard.writeText(letter).then(() => { note = "Copied. Read it over before you send it."; render(); }); return; }
      if (a === "letter") {
        letter = null; note = ""; render();
        send({ type: "cover-letter", source: job.source, id: job.id }, (r) => {
          letter = (r && r.letter) || "";
          note = r && r.letter ? "Written from your résumés only. Change the résumé or tone in the app." : (r && r.error) || "Couldn't write it.";
          render();
        });
        return;
      }
      const st = data && data.job.status === a ? "" : a;
      send({ type: "set-status", source: job.source, id: job.id, status: st }, (r) => {
        if (r && r.mark) { marks.set(job.id, r.mark); data.job.status = st; applyStamps(); }
        render();
      });
    }
    return {
      status, tagFor,
      setVisible(v) { showTag = v; if (!v && shown) { box.remove(); shown = false; } },
      job(j) {
        if (j && job && j.id === job.id) return;
        job = j; data = null; note = ""; busy = false; letter = "";
        if (!j) { status(null, "watching"); wrap.classList.remove("open"); }
        render();
      },
      captured(m) {
        // the app scored the posting that's open: show it, and let Claude read it if it's worth a look
        if (!job || m.id !== job.id) return;
        tagFor(m);
        if (wrap.classList.contains("open")) refresh();
        if (!analysisAsked.has(m.id) && m.has_description && !m.analyzed) { analysisAsked.add(m.id); analyze(true); }
      },
      busy: () => busy,
    };
  })();

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg.type === "scanner-status") {
      if (!msg.ok) { panel.status("bad", msg.error && /reach/i.test(msg.error) ? "not connected" : "not paired"); for (const id of msg.forget || []) sent.delete(id); return; }
      for (const m of msg.marks || []) {
        if (m.source !== site.source) continue;
        marks.set(m.id, m);
        panel.captured(m);
      }
      applyStamps();
      if (!currentId || !marks.has(currentId)) panel.status("ok", `${marks.size} captured`);
    } else if (msg.type === "scan-now") {
      scanCards(); scanItem(true);
      reply({ ok: true, site: site.source, cards: site.cards().length, posting: currentId });
    } else if (msg.type === "diagnostics") {
      const cards = site.cards().slice(0, 8).map((c) => { let r = null; try { r = site.card(c.el, c); } catch (e) { r = { error: String(e) }; } return { id: c.id, ...r }; });
      const cur = site.current();
      let item = null;
      try { item = cur && site.item(cur.root); } catch (e) { item = { error: String(e) }; }
      if (item && item.description) item.description = item.description.slice(0, 300) + "…";
      reply({ extension: chrome.runtime.getManifest().version, site: site.source, path: location.pathname, cards_found: site.cards().length,
        cards, current: cur && { id: cur.id, url: cur.url }, item, json_ld: !!jsonLdJob() });
    }
  });

  chrome.storage.local.get({ enabled: true, indicator: true, dimSkip: false }, (s) => {
    enabled = s.enabled; dimSkip = s.dimSkip;
    panel.setVisible(s.indicator);
    if (site === GENERIC) { panel.status(null, "scanning this page"); scanItem(true); return; }
    panel.status(null, enabled ? "watching" : "paused");
    if (enabled) schedule();
  });
  chrome.storage.onChanged.addListener((ch) => {
    if (ch.enabled) { enabled = ch.enabled.newValue; panel.status(null, enabled ? "watching" : "paused"); if (enabled) schedule(); }
    if (ch.indicator) panel.setVisible(ch.indicator.newValue);
    if (ch.dimSkip) { dimSkip = ch.dimSkip.newValue; applyStamps(); }
  });

  if (site !== GENERIC) {
    new MutationObserver((muts) => {
      // our own stamps and panel changing shouldn't trigger a rescan
      if (muts.every((m) => [...m.addedNodes, ...m.removedNodes].every((n) => n.dataset && (n.dataset.jobScanner !== undefined)))) return;
      schedule();
    }).observe(document.documentElement, { childList: true, subtree: true });
    addEventListener("scroll", schedule, { passive: true });
    let lastUrl = location.href;
    setInterval(() => { if (location.href !== lastUrl) { lastUrl = location.href; schedule(); } }, 800);
  }

  window.__jobScanner = { scanNow: () => { scanCards(); scanItem(true); } };
})();
