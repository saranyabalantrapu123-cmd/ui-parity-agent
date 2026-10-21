// Page inventory extractor, evaluated in the browser by Playwright.
// Uses semantic HTML first (main/nav/header, aria-labels, forms, buttons) and falls back to
// class/id/text heuristics so it also works on real-world sites with no data- attributes.
() => {
  const CHAT_RE = /(chat|chatbot|assistant|livechat|messenger|intercom|drift|zendesk|ada-embed|virtual[-_ ]?agent|bot-launcher)/i;
  const CHAT_TEXT_RE = /^(ask|chat with)\s+\w+|\b(live chat|chat now|virtual assistant)\b/i;
  // Class/id tokens such as "hero", "promo-banner", "site-announcement", "promo-strip".
  const BANNER_TOKEN_RE = /^((.*[-_])?(banner|promo|promotion|hero|announcement|notice)|promo[-_].*)$/i;
  const CARD_TOKEN_RE = /^(.*[-_])?(card|tile)$/i;
  const CTA_TOKEN_RE = /(^|[-_])(btn|button|cta)([-_]|$)/i;
  const CHROME_SEL = "header, nav, footer, [role=banner], [role=navigation], [role=contentinfo]";

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const cls = (el) => (typeof el.className === "string" ? el.className : (el.getAttribute("class") || ""));
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const attrText = (el) => [
    el.id, cls(el), el.getAttribute("aria-label"), el.getAttribute("data-component"),
    el.getAttribute("data-testid"), el.tagName === "IFRAME" ? `${el.src} ${el.title}` : "",
  ].filter(Boolean).join(" ");
  const firstHeading = (el, sel = "h1,h2,h3,h4") => {
    const h = el.querySelector(sel);
    return h ? clean(h.innerText) : "";
  };
  const hint = (el) => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : "") +
    (cls(el) ? "." + cls(el).trim().split(/\s+/).slice(0, 2).join(".") : "");

  // ---------------------------------------------------------------- chatbot detection
  const chatCandidates = [];
  for (const el of document.querySelectorAll("body *")) {
    if (["SCRIPT", "STYLE", "LINK", "META"].includes(el.tagName)) continue;
    if (el.closest("nav, [role=navigation]")) continue; // nav links to a support page are not widgets
    const byAttr = CHAT_RE.test(attrText(el));
    const isControl = el.matches("button, [role=button], a.btn, a[class*=button]");
    const byText = isControl && CHAT_TEXT_RE.test(clean(el.innerText));
    if ((byAttr || byText) && isVisible(el)) chatCandidates.push(el);
  }
  // Keep only the outermost element of each widget.
  const chatRoots = chatCandidates.filter((el) => !chatCandidates.some((o) => o !== el && o.contains(el)));
  const isFixed = (el) => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const p = getComputedStyle(n).position;
      if (p === "fixed") return true;
    }
    return false;
  };
  const chats = chatRoots.map((el) => {
    const r = el.getBoundingClientRect();
    const inHeader = !!el.closest("header, [role=banner]");
    return {
      label: clean(el.getAttribute("aria-label") || el.innerText).slice(0, 80),
      selector_hint: hint(el),
      bbox: { x: r.x, y: r.y + window.scrollY, width: r.width, height: r.height, viewport_y: r.y },
      fixed: isFixed(el) && !inHeader,
      in_header: inHeader,
      in_main: !!el.closest("main, [role=main]"),
    };
  });

  // ---------------------------------------------------------------- nav + links
  const nav = [];
  for (const a of document.querySelectorAll("nav a[href], [role=navigation] a[href], header a[href]")) {
    const label = clean(a.getAttribute("aria-label") || a.innerText);
    if (label) nav.push({ label, href: a.href });
  }
  const links = [...new Set([...document.querySelectorAll("a[href]")].map((a) => a.href))];

  // ---------------------------------------------------------------- components in main content
  const root = document.querySelector("main, [role=main]") || document.body;
  const inChat = (el) => chatRoots.some((c) => c === el || c.contains(el));
  const inChrome = (el) => root === document.body && !!el.closest(CHROME_SEL);

  const ids = new Map();
  const components = [];
  let nextId = 1;

  const classify = (el) => {
    const tag = el.tagName;
    const tokens = cls(el).split(/\s+/).filter(Boolean);
    if (tag === "FORM") return "form";
    if (["SECTION", "DIV", "ASIDE"].includes(tag) && [el.id, ...tokens].some((t) => t && BANNER_TOKEN_RE.test(t))) return "banner";
    if (tag === "ARTICLE" || tokens.some((t) => CARD_TOKEN_RE.test(t))) return "card";
    if (["SECTION", "ASIDE"].includes(tag) &&
        (el.getAttribute("aria-label") || [...el.children].some((c) => /^H[2-3]$/.test(c.tagName)))) return "region";
    if (tag === "BUTTON" || el.getAttribute("role") === "button" ||
        (tag === "INPUT" && ["submit", "button"].includes(el.type)) ||
        (tag === "A" && tokens.some((t) => CTA_TOKEN_RE.test(t)))) return "cta";
    if (/^H[1-3]$/.test(tag)) return "heading";
    return null;
  };

  const fieldLabel = (input) => {
    if (input.labels && input.labels.length) return clean(input.labels[0].innerText);
    return clean(input.getAttribute("aria-label") || input.placeholder || input.name || "");
  };

  for (const el of root.querySelectorAll("*")) {
    if (inChat(el) || inChrome(el) || !isVisible(el)) continue;
    const kind = classify(el);
    if (!kind) continue;
    let parent = null;
    let context = "";
    for (let n = el.parentElement; n && n !== root.parentElement; n = n.parentElement) {
      if (ids.has(n)) {
        const pc = components[ids.get(n) - 1];
        if (parent === null) parent = pc.id;
        if (!context && pc.kind !== "heading" && pc.name) context = pc.name;
        if (parent !== null && context) break;
      }
    }
    let name = "";
    const comp = { id: nextId, kind, name, parent, context, fields: [], href: null };
    if (kind === "form") {
      comp.fields = [...el.querySelectorAll("input, select, textarea")]
        .filter((i) => !["hidden", "submit", "button"].includes(i.type))
        .map(fieldLabel).filter(Boolean);
      const legend = el.querySelector("legend");
      name = el.getAttribute("aria-label") || (legend && legend.innerText) || firstHeading(el) || el.id || "form";
    } else if (kind === "banner" || kind === "region") {
      name = el.getAttribute("aria-label") || firstHeading(el) || clean(el.innerText).slice(0, 60);
    } else if (kind === "card") {
      name = firstHeading(el, "h2,h3,h4") || el.getAttribute("aria-label") || clean(el.innerText).slice(0, 60);
    } else if (kind === "cta") {
      name = el.getAttribute("aria-label") || el.innerText || el.value || "";
      if (el.tagName === "A") comp.href = el.href;
    } else {
      name = el.innerText;
    }
    comp.name = clean(name);
    if (!comp.name) continue;
    ids.set(el, nextId);
    components.push(comp);
    nextId += 1;
  }

  const h1 = document.querySelector("h1");
  return {
    title: clean(document.title),
    h1: h1 ? clean(h1.innerText) : "",
    nav,
    links,
    components,
    chats,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
}
