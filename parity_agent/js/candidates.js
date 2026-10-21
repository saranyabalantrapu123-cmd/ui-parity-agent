// Lists clickable elements for goal-driven flow navigation. Each candidate is tagged with a
// data-parity-idx attribute so Python can click exactly the element the navigator picked.
() => {
  const CHAT_RE = /(chat|chatbot|assistant|livechat|messenger|intercom|drift|zendesk)/i;
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const cls = (el) => (typeof el.className === "string" ? el.className : "");
  const inChat = (el) => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      if (CHAT_RE.test(`${n.id} ${cls(n)} ${n.getAttribute("aria-label") || ""}`)) return true;
    }
    return false;
  };
  const contextOf = (el) => {
    const box = el.closest("article, [class*=card], section, form");
    if (!box) return "";
    const h = box.querySelector("h1, h2, h3, h4");
    return clean(box.getAttribute("aria-label") || (h && h.innerText) || "");
  };
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll("a[href], button, [role=button], input[type=submit]")) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === "hidden" || el.disabled || inChat(el)) continue;
    const label = clean(el.getAttribute("aria-label") || el.innerText || el.value);
    if (!label) continue;
    el.setAttribute("data-parity-idx", String(i));
    out.push({
      index: i,
      label,
      context: contextOf(el),
      href: el.tagName === "A" ? el.href : null,
      submits: el.type === "submit" || (el.tagName === "BUTTON" && !!el.form && el.type !== "button"),
    });
    i += 1;
  }
  return out;
}
