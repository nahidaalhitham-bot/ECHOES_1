/* Guard: caregiver pages require a session. Redirect to /login otherwise.
   Returns a promise so callers can await the check before rendering. */
async function requireAuth() {
  try { if (localStorage.getItem('echoes_role') === 'patient') { location.replace('/patient'); await new Promise(() => {}); } } catch (e) {}
  const s = await fetch('/api/auth/status').then(r => r.json());
  if (!s.authenticated) {
    location.href = '/login';
    // Never resolve: the page is navigating away. Avoids an uncaught
    // "not authenticated" error in the console on every guarded page.
    await new Promise(() => {});
  }
  return s.user;
}

function shell(active, title, subtitle) {
  const groups = [
    { title: "الرئيسية", items: [["dashboard", "/dashboard", "نظرة عامة", "◈"]] },
    { title: "الذاكرة والتذكير", items: [
      ["profile", "/profile", "ملف المريض", "▤"],
      ["family", "/family", "الأشخاص المهمون", "◔"],
      ["network", "/network", "شبكة الذكريات", "◍"],
      ["camera", "/camera", "المساعد والكاميرا", "◐"],
    ]},
    { title: "الموقع والأمان", items: [
      ["gps", "/safety", "الموقع المباشر", "◉"],
      ["emergency", "/emergency-center", "التنبيهات والأمان", "✚"],
    ]},
    { title: "الإدارة", items: [
      ["caregivers", "/caregivers", "المسؤولون", "◔"],
      ["device", "/device", "حالة الجهاز", "▣"],
      ["settings", "/settings", "الإعدادات", "⚙"],
      ["code", "/code", "معلومات المشروع", "</>"],
    ]},
  ];
  const nav = groups.map(group => `<li class="nav-group-title">${group.title}</li>` + group.items.map(([k, href, label, ico]) =>
    `<li><a href="${href}" class="${k === active ? 'active' : ''}">` +
    `<span class="ico">${ico}</span><span>${label}</span></a></li>`
  ).join("")).join("");

  return `
  <div class="app">
    <aside class="sidebar">
      <div class="brand"><img class="brand-ribbon" src="/static/echoes-ribbon.svg" alt=""/><span>ECHOES</span><small>Every Object Holds Our Stories</small></div>
      <ul class="nav">${nav}</ul>
    </aside>
    <main class="content">
      <div class="topbar">
        <div>
          <h1>${title}</h1>
          <p class="sub">${subtitle || ""}</p>
        </div>
      </div>
      <div id="page"></div>
    </main>
  </div>`;
}

async function jget(url) {
  const r = await fetch(url);
  if (r.status === 401) {
    location.href = '/login';
    return new Promise(() => {});
  }
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

async function jsend(url, method, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.status === 204 ? null : r.json();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s == null ? "" : s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
