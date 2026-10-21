/* Job Scanner: fills an application form with your details, only when you click "Fill this application" in the
   extension's popup. It types into empty fields and attaches your tailored résumé and cover letter where the form
   asks for them. It never overwrites what's there, never clicks, and never submits: you check it and send it.
   Questions about gender, race, ethnicity, veterans, disability and the like are always left to you. */
(() => {
  "use strict";
  if (window.__jobScannerFill) return;

  const clean = (s, n = 300) => String(s || "").replace(/\s+/g, " ").trim().slice(0, n);
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };
  const PERSONAL = /\b(gender|sex\b|pronoun|race|racial|ethnic|hispanic|latin[ox]|veteran|disab|sexual orientation|transgender|date of birth|birth ?date|social security|ssn|religio|marital|criminal|convict|felony|arrest|signature)/i;
  const FILLED = "2px solid #0f6b4f", DRAFTED = "2px solid #b7791f";

  /* ---------- what a field is asking ---------- */
  function words(s) { return clean(String(s || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-[\]]+/g, " ")); }
  function labelOf(el) {
    const parts = [];
    if (el.labels && el.labels.length) parts.push([...el.labels].map((l) => l.innerText).join(" "));
    const by = el.getAttribute("aria-labelledby");
    if (by) parts.push(by.split(/\s+/).map((id) => (document.getElementById(id) || {}).innerText || "").join(" "));
    if (el.getAttribute("aria-label")) parts.push(el.getAttribute("aria-label"));
    if (el.type === "radio" || el.type === "checkbox") {
      const fs = el.closest("fieldset");
      const legend = fs && fs.querySelector("legend");
      if (legend) parts.unshift(legend.innerText);
    }
    if (!clean(parts.join(" "))) {
      // no label element: the nearest short text above the field in its container
      let node = el.parentElement;
      for (let i = 0; i < 4 && node && !clean(parts.join(" ")); i++, node = node.parentElement) {
        const t = clean(node.innerText, 400);
        if (t && t.length < 300) parts.push(t);
      }
    }
    if (el.placeholder) parts.push(el.placeholder);
    if (!clean(parts.join(" "))) parts.push(words(el.name || el.id));
    return clean(parts.join(" "), 400);
  }

  // [key, pattern]: first match wins, so the narrow ones come first
  const RULES = [
    ["cover_letter", /cover ?letter/i],
    ["resume_file", /r[eé]sum[eé]|\bcv\b|curriculum/i],
    ["sponsorship", /sponsor/i],
    ["work_authorized", /authori[sz]ed to work|eligible to work|right to work|work authori[sz]ation|legally (able|permitted) to work/i],
    ["relocate", /relocat/i],
    ["over_18", /\b18\b.*(years|older|age)|over 18|at least 18/i],
    ["first_name", /first name|given name|^first\b|\bfname\b|preferred first/i],
    ["last_name", /last name|surname|family name|\blname\b/i],
    ["email", /e-?mail/i],
    ["phone", /phone|mobile|cell\b|telephone/i],
    ["linkedin", /linked ?in/i],
    ["github", /github/i],
    ["website", /website|portfolio|personal (site|url|page)|\bblog\b/i],
    ["street", /street|address( line)? ?1|^address$|mailing address/i],
    ["postal_code", /zip|postal|post code/i],
    ["city", /\bcity\b|\btown\b/i],
    ["state", /\bstate\b(?! of)|province|\bregion\b/i],
    ["country", /\bcountry\b/i],
    ["location", /location|where (are you|do you) (live|located|based)/i],
    ["current_company", /current (company|employer)|most recent (company|employer)|present employer/i],
    ["current_title", /current (job )?(title|position|role)|most recent (job )?(title|position)/i],
    ["school", /school|university|college|institution/i],
    ["degree", /degree/i],
    ["start_date", /start date|available to start|earliest (start|date)|when can you start|notice period/i],
    ["salary_expectation", /salary|compensation|pay expectation|desired pay|expected pay/i],
    ["how_heard", /how did you (hear|find|learn)|where did you (hear|find|see)/i],
    ["full_name", /^(full |legal |your )?name\b|full name|legal name/i],
  ];
  const NOT_PERSON = /company|employer|school|manager|reference|emergency|recruiter|referr/i;

  const SHORT_ONLY = new Set(["first_name", "last_name", "full_name", "email", "phone", "linkedin", "github", "website",
    "street", "postal_code", "city", "state", "country", "location", "current_company", "current_title", "school", "degree"]);

  function keyFor(el, label) {
    if (el.type === "email") return "email";
    if (el.type === "tel") return "phone";
    if (el.type === "file") return /cover/i.test(label) ? "cover_file" : RULES[1][1].test(label) ? "resume_file" : "";
    for (const [key, re] of RULES) {
      if (!re.test(label)) continue;
      if (key === "resume_file") continue; // résumé text boxes are for pasting: left to you
      if (["first_name", "last_name", "full_name"].includes(key) && NOT_PERSON.test(label)) continue;
      if (SHORT_ONLY.has(key) && (label.length > 80 || (/\?/.test(label) && label.length > 40))) return ""; // "Please state why…" is a question
      if (key === "cover_letter" && el.tagName !== "TEXTAREA") return "";
      return key;
    }
    return "";
  }

  /* ---------- writing into a field the way a person typing would ---------- */
  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    el.focus({ preventScroll: true });
    setter.call(el, value); // React and friends watch the native setter
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.blur();
  }
  const mark = (el, how) => { el.style.outline = how; el.style.outlineOffset = "1px"; };
  const norm = (s) => clean(s).toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

  function pickOption(select, value) {
    const want = norm(value);
    if (!want) return false;
    const opts = [...select.options].filter((o) => o.value !== "" && !/^(select|choose|please)/i.test(o.text));
    const yesNo = /^(yes|no)$/.test(want);
    const num = /^\d+(\.\d+)?$/.test(want) ? parseFloat(want) : null;
    const inRange = (t) => {
      let m;
      if ((m = /(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)/.exec(t))) return num >= +m[1] && num <= +m[2];
      if ((m = /(\d+)\s*(?:\+|or more|and (?:up|above)|plus)/i.exec(t))) return num >= +m[1];
      if ((m = /(?:less than|under|fewer than|<)\s*(\d+)/i.exec(t))) return num < +m[1];
      return false;
    };
    const hit = opts.find((o) => norm(o.text) === want) ||
      (num != null ? opts.find((o) => inRange(o.text)) : null) ||
      (yesNo ? opts.find((o) => norm(o.text).startsWith(want + " ") || norm(o.text) === want)
        : opts.find((o) => norm(o.text).startsWith(want) || want.startsWith(norm(o.text))));
    if (!hit) return false;
    setValue(select, hit.value);
    return true;
  }
  function pickRadio(radios, value) {
    const want = norm(value);
    const hit = radios.find((r) => { const t = norm(radioText(r)); return t === want || t.startsWith(want + " "); });
    if (!hit) return false;
    hit.click(); // choosing a radio button is the one way to set it that sites reliably notice; this isn't a submit
    return true;
  }
  const radioText = (r) => clean((r.labels && r.labels[0] && r.labels[0].innerText) || r.getAttribute("aria-label") || r.value);

  function fileFrom(b64, name) {
    const bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name, { type: "application/pdf" });
  }
  function attach(input, file) {
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return input.files.length === 1;
    } catch (_) { return false; }
  }

  /* ---------- the form ---------- */
  function fields() {
    const out = [];
    const radioGroups = new Map();
    for (const el of document.querySelectorAll("input, textarea, select")) {
      if (el.disabled || el.readOnly) continue;
      const type = (el.type || "").toLowerCase();
      if (["hidden", "submit", "button", "reset", "image", "password", "search", "checkbox"].includes(type)) continue;
      if (type !== "file" && !visible(el)) continue;
      if (type === "radio") {
        const name = el.name || el.closest("fieldset, [role=radiogroup]")?.id || "";
        if (!name) continue;
        if (!radioGroups.has(name)) { radioGroups.set(name, []); out.push({ el, radios: radioGroups.get(name) }); }
        radioGroups.get(name).push(el);
        continue;
      }
      out.push({ el });
    }
    for (const f of out) {
      if (f.radios) {
        const fs = f.el.closest("fieldset, [role=radiogroup]");
        f.label = clean(fs ? (fs.querySelector("legend") || {}).innerText || fs.getAttribute("aria-label") || labelOf(f.el) : labelOf(f.el), 400);
      } else {
        f.label = labelOf(f.el);
      }
    }
    return out;
  }
  const isEmpty = (f) => f.radios ? !f.radios.some((r) => r.checked)
    : f.el.type === "file" ? !(f.el.files && f.el.files.length)
    : f.el.tagName === "SELECT" ? !f.el.value || /^(select|choose|please)/i.test(f.el.selectedOptions[0]?.text || "")
    : !String(f.el.value || "").trim();
  const looksLikeQuestion = (label) => label.length >= 12 && (/\?/.test(label) || /^(describe|explain|tell|why|what|how|please (describe|explain|tell|share)|share|list)\b/i.test(label) || /years of experience/i.test(label));
  function optionsOf(f) {
    if (f.radios) return f.radios.map(radioText).filter(Boolean);
    if (f.el.tagName === "SELECT") return [...f.el.options].map((o) => clean(o.text, 80)).filter((t) => t && !/^(select|choose|please)/i.test(t));
    return [];
  }

  let pending = []; // questions left for Claude: [{f, text}]

  function fill(data) {
    const a = data.fields || {};
    const values = { ...a };
    values.full_name = [a.first_name, a.last_name].filter(Boolean).join(" ");
    values.location = [a.city, a.state].filter(Boolean).join(", ");
    for (const k of ["work_authorized", "sponsorship", "relocate", "over_18"]) if (a[k]) values[k] = a[k] === "yes" ? "Yes" : "No";
    const answers = (data.answers || []).map((x) => ({ ...x, n: new Set(norm(x.question).split(" ").filter((w) => w.length > 3)) }));

    const report = { filled: [], attached: [], personal: [], questions: [], frame: location.hostname, frames: [] };
    pending = [];
    for (const f of fields()) {
      if (!isEmpty(f)) continue;
      const label = f.label;
      if (PERSONAL.test(label)) { report.personal.push(clean(label, 80)); continue; }
      const key = keyFor(f.el, label);
      if (key === "resume_file" || key === "cover_file") {
        const file = key === "resume_file" ? data.resume_pdf : data.letter_pdf;
        if (file && attach(f.el, fileFrom(file.data, file.name))) { report.attached.push(key === "resume_file" ? "Tailored résumé" : "Cover letter"); }
        continue;
      }
      let value = key === "cover_letter" ? data.letter : key ? values[key] : "";
      let how = FILLED;
      if (!value) {
        // a question the packet already answered?
        const qn = new Set(norm(label).split(" ").filter((w) => w.length > 3));
        let best = null, bestScore = 0;
        for (const x of answers) {
          const shared = [...qn].filter((w) => x.n.has(w)).length;
          const score = shared / Math.max(1, Math.min(qn.size, x.n.size));
          if (score > bestScore) { best = x; bestScore = score; }
        }
        if (best && bestScore >= 0.6 && qn.size >= 2) { value = best.answer; how = DRAFTED; }
      }
      if (!value) {
        if (looksLikeQuestion(label) || (f.el.tagName === "TEXTAREA" && label.length >= 8)) {
          pending.push({ f, text: label });
          report.questions.push(label);
        }
        continue;
      }
      if (put(f, value, how)) report.filled.push(clean(label, 60));
      else if (how === DRAFTED) { pending.push({ f, text: label }); report.questions.push(label); } // its options didn't fit the answer
    }
    if (window === top) {
      report.frames = [...document.querySelectorAll("iframe")].map((i) => { try { return new URL(i.src, location.href); } catch (_) { return null; } })
        .filter((u) => u && /^https:$/.test(u.protocol) && u.hostname !== location.hostname).map((u) => u.hostname);
      report.frames = [...new Set(report.frames)].slice(0, 5);
    }
    return report;
  }

  function put(f, value, how) {
    let ok = false;
    if (f.radios) ok = pickRadio(f.radios, value);
    else if (f.el.tagName === "SELECT") ok = pickOption(f.el, value);
    else if (f.el.type === "date" || f.el.type === "number") ok = false; // formats vary: left to you
    else { setValue(f.el, value); ok = true; }
    if (ok) mark(f.radios ? f.radios[0].closest("fieldset") || f.radios[0] : f.el, how);
    return ok;
  }

  // Claude's answers to this frame's questions, matched back by question text
  function answer(items) {
    let n = 0;
    const byQ = new Map(items.filter((x) => x.answer).map((x) => [norm(x.question), x.answer]));
    const qs = questions();
    for (const [i, p] of pending.entries()) {
      const v = byQ.get(norm(qs[i])) || byQ.get(norm(p.text));
      if (v && isEmpty(p.f) && put(p.f, v, DRAFTED)) n++;
    }
    return n;
  }
  const questions = () => pending.map((p) => { const o = optionsOf(p.f); return o.length ? `${p.text} (options: ${o.join(" | ")})` : p.text; });

  function banner(text) {
    if (window !== top) return;
    let host = document.getElementById("job-scanner-fill");
    if (!host) {
      host = document.createElement("div");
      host.id = "job-scanner-fill";
      host.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:2147483647";
      document.documentElement.appendChild(host);
      host.attachShadow({ mode: "open" }).innerHTML = `<style>div{font:13px/1.4 system-ui,sans-serif;background:#0f6b4f;color:#fff;padding:10px 14px;border-radius:10px;max-width:360px;box-shadow:0 4px 16px rgba(0,0,0,.25)}button{margin-left:10px;background:none;border:1px solid #fff8;color:#fff;border-radius:6px;cursor:pointer}</style><div><span></span><button type="button">OK</button></div>`;
      host.shadowRoot.querySelector("button").addEventListener("click", () => host.remove());
    }
    host.shadowRoot.querySelector("span").textContent = text;
  }

  window.__jobScannerFill = fill;
  window.__jobScannerAnswer = answer;
  window.__jobScannerQuestions = questions;
  window.__jobScannerBanner = banner;
})();
