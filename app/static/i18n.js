/* ECHOES — interface language (العربية / English).
 *
 * The app is written in Arabic. In English mode this script translates the
 * interface in the browser from a dictionary (/i18n/en.json, built from
 * app/i18n/*.tsv) and keeps translating whatever the pages add later.
 * Text it has no translation for (names, memories the family typed) is left
 * exactly as written — it never produces half-translated sentences.
 * The choice is remembered per browser (localStorage "echoes_lang").
 */
(function () {
  const KEY = 'echoes_lang';
  const AR = /[؀-ۿ]/;
  const ARW = '\\u0600-\\u06FF';
  let lang = 'ar';
  try { lang = localStorage.getItem(KEY) || 'ar'; } catch (e) {}
  window.ECHOES_LANG = lang;

  window.echoesSetLang = function (l) {
    try { localStorage.setItem(KEY, l); } catch (e) {}
    location.reload();
  };

  function addToggle() {
    if (document.getElementById('echoesLangBtn')) return;
    const b = document.createElement('button');
    b.id = 'echoesLangBtn';
    b.type = 'button';
    b.setAttribute('data-noi18n', '');
    b.textContent = lang === 'en' ? 'العربية' : 'English';
    b.title = lang === 'en' ? 'التبديل إلى العربية' : 'Switch to English';
    b.style.cssText = 'position:fixed;bottom:14px;left:14px;z-index:99999;padding:7px 14px;' +
      'border-radius:999px;border:1px solid #b88ce0;background:#fff;color:#3b1d5c;font:700 13px system-ui,sans-serif;' +
      'box-shadow:0 2px 10px rgba(60,20,90,.18);cursor:pointer';
    b.onclick = () => window.echoesSetLang(lang === 'en' ? 'ar' : 'en');
    document.body.appendChild(b);
  }

  if (lang !== 'en') {
    document.addEventListener('DOMContentLoaded', addToggle);
    return;
  }

  // ---------------- English mode ----------------
  const html = document.documentElement;
  html.lang = 'en';
  html.dir = 'ltr';
  const hide = document.createElement('style');
  hide.textContent = 'body{visibility:hidden}';
  html.appendChild(hide);
  setTimeout(() => hide.remove(), 2500);   // never leave the page hidden

  // Dictionary: cached per app version, loaded synchronously so pages don't flash Arabic.
  let dict = {};
  try {
    const cached = JSON.parse(localStorage.getItem('echoes_i18n_en') || 'null');
    const x = new XMLHttpRequest();
    x.open('GET', '/i18n/en.json?v=' + (cached ? cached.v : '0'), false);
    x.send();
    if (x.status === 200) {
      const d = JSON.parse(x.responseText);
      dict = d.dict; try { localStorage.setItem('echoes_i18n_en', x.responseText); } catch (e) {}
    } else if (cached) dict = cached.dict;
  } catch (e) {
    try { dict = JSON.parse(localStorage.getItem('echoes_i18n_en')).dict; } catch (e2) {}
  }

  const norm = s => s.replace(/\s+/g, ' ').trim();
  const exact = new Map(), patterns = new Map();
  for (const [k, v] of Object.entries(dict)) {
    const nk = norm(k);
    if (nk.includes('{n}') || nk.includes('{q}')) patterns.set(nk, v);
    exact.set(nk, v);
  }
  const keys = [...exact.keys()].filter(k => k.length >= 2 && !k.includes('{') && AR.test(k))
    .sort((a, b) => b.length - a.length);
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  let compRe = null;
  try {
    compRe = new RegExp('(?<![' + ARW + '])(' + keys.map(escRe).join('|') + ')(?![' + ARW + '])', 'g');
  } catch (e) { compRe = null; }

  const toLatin = s => s.replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  const cache = new Map();

  // Patterns: {n} number, {q} text inside «», {w} one Arabic word (a name).
  const patRes = [];
  for (const [k, v] of patterns) {
    const types = [];
    const src = k.split(/(\{[nqw]\})/).map(part => {
      if (part === '{n}') { types.push('n'); return '([0-9]+(?:[.,:\\-][0-9]+)*)'; }
      if (part === '{q}') { types.push('q'); return '([^»]*)'; }
      if (part === '{w}') { types.push('w'); return '([' + ARW + ']+)'; }
      return escRe(part);
    }).join('');
    try { patRes.push({ re: new RegExp('^' + src + '$'), types, v }); } catch (e) {}
  }
  function viaPattern(t) {
    const lt = toLatin(t);
    for (const p of patRes) {
      const m = lt.match(p.re);
      if (!m) continue;
      const vals = { n: [], q: [], w: [] };
      p.types.forEach((ty, i) => vals[ty].push(m[i + 1]));
      const idx = { n: 0, q: 0, w: 0 };
      return p.v.replace(/\{([nqw])\}/g, (_, ty) => {
        const x = vals[ty][idx[ty]++] || '';
        return ty === 'n' ? x : (exact.get(norm(x)) || x);
      });
    }
    return null;
  }

  function viaComposite(t) {
    if (!compRe) return null;
    const out = toLatin(t).replace(compRe, m => exact.get(m));
    // Accept only if nothing Arabic is left, except quoted names («…»).
    return AR.test(out.replace(/«[^»]*»/g, '')) ? null : out;
  }

  function tr(text) {
    if (!text || !AR.test(text)) return null;
    const t = norm(text);
    if (cache.has(t)) return cache.get(t);
    let r = exact.get(t);
    if (r == null) r = viaPattern(t);
    if (r == null && /^[—–-]\s/.test(t)) { const rest = tr(t.replace(/^[—–-]\s*/, '')); if (rest) r = '— ' + rest; }
    if (r == null) r = viaComposite(t);
    if (r == null) r = null;
    cache.set(t, r);
    return r;
  }
  window.echoesT = s => tr(s) || s;   // for scripts that build messages

  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE', 'NOSCRIPT']);
  function skipEl(el, forAttrs) {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (forAttrs && e === el && e.tagName === 'TEXTAREA') continue;   // its placeholder is UI
      if (SKIP.has(e.tagName) || e.isContentEditable || (e.hasAttribute && e.hasAttribute('data-noi18n'))) return true;
    }
    return false;
  }

  function doText(node) {
    const v = node.nodeValue;
    if (!AR.test(v) || skipEl(node.parentElement)) return;
    const r = tr(v);
    if (r != null) {
      const lead = v.match(/^\s*/)[0], trail = v.match(/\s*$/)[0];
      const nv = lead + r + trail;
      if (nv !== v) node.nodeValue = nv;   // never re-set identical text (would loop)
    }
  }
  const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  function doAttrs(el) {
    if (skipEl(el, true)) return;
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v && AR.test(v)) { const r = tr(v); if (r != null && r !== v) el.setAttribute(a, r); }
    }
    if (el.tagName === 'INPUT' && /^(button|submit|reset)$/i.test(el.type) && AR.test(el.value)) {
      const r = tr(el.value); if (r != null && r !== el.value) el.value = r;
    }
  }
  function walk(root) {
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1) return;
    if (SKIP.has(root.tagName)) { doAttrs(root); return; }
    doAttrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) doText(n); else doAttrs(n);
    }
  }

  // Native dialogs too.
  const _alert = window.alert, _confirm = window.confirm, _prompt = window.prompt;
  window.alert = m => _alert.call(window, window.echoesT(String(m)));
  window.confirm = m => _confirm.call(window, window.echoesT(String(m)));
  window.prompt = (m, d) => _prompt.call(window, window.echoesT(String(m)), d);

  function start() {
    if (AR.test(document.title)) { const r = tr(document.title); if (r) document.title = r; }
    walk(document.body);
    hide.remove();
    addToggle();
    new MutationObserver(muts => {
      for (const m of muts) {
        if (m.type === 'characterData') doText(m.target);
        else if (m.type === 'attributes') doAttrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true,
                                attributes: true, attributeFilter: ATTRS });
    // Titles set from script after load
    new MutationObserver(() => {
      if (AR.test(document.title)) { const r = tr(document.title); if (r) document.title = r; }
    }).observe(document.querySelector('title') || html, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
