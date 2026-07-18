(() => {
  const API = "/api/v1";
  const ADMIN = "/admin";
  /** Secret SPA path from server-injected config (rotate via ADMIN_UI_SLUG env). */
  const ADMIN_UI_SLUG =
    (typeof window !== "undefined" && window.__MRDEV_CFG__ && window.__MRDEV_CFG__.adminUiSlug) ||
    "ops-x9k2m7q4";
  const ADMIN_UI = `#/${ADMIN_UI_SLUG}`;
  const S = {
    adminToken: "mrdev_admin_token_v2",
    userKey: "mrdev_user_api_key",
    theme: "mrdev_theme",
  };

  function getTheme() {
    try {
      const v = localStorage.getItem(S.theme);
      return v === "dark" ? "dark" : "light";
    } catch (_e) {
      return "light";
    }
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(S.theme, next);
    } catch (_e) {
      /* ignore */
    }
  }

  applyTheme(getTheme());
  const I18N = window.MrdevI18n || {
    SUPPORTED: ["zh", "en", "ru", "vi"],
    LABELS: { zh: "中文", en: "EN", ru: "RU", vi: "VI" },
    t: (k) => k,
    setLang: (l) => l,
    getLang: () => "zh",
    localeTag: () => "zh-CN",
  };
  const t = (...args) => I18N.t(...args);
  // Drop legacy session keys so old tokens cannot keep the UI "logged in".
  try {
    localStorage.removeItem("mrdev_admin_token");
  } catch (_e) {
    /* ignore */
  }

  const app = document.getElementById("app");
  const nav = document.getElementById("main-nav");

  const esc = (s) =>
    String(s ?? "")
      .split("&").join("&amp;")
      .split("<").join("&lt;")
      .split(">").join("&gt;")
      .split('"').join("&quot;");
  const num = (n) => (n == null ? "—" : Number(n).toLocaleString(I18N.localeTag()));

  function adminToken() {
    return localStorage.getItem(S.adminToken) || "";
  }
  function userKey() {
    return localStorage.getItem(S.userKey) || "";
  }

  function isAdminUiHash(hash) {
    return hash === ADMIN_UI || hash.startsWith(`${ADMIN_UI}/`);
  }

  function isLegacyAdminHash(hash) {
    const h = hash || "";
    return h === "#admin" || h === "#/admin" || h.startsWith("#/admin/") || h.startsWith("#admin/");
  }

  function setNav() {
    const hash = location.hash || "#/";
    const items = [
      { href: "#/", label: t("nav.home") },
      { href: "#/docs", label: t("nav.docs") },
      { href: "#/user", label: t("nav.user") },
      { href: "#/chat", label: t("nav.chat") },
      { href: "#/usage", label: t("nav.usage") },
    ];
    // Only show dashboard when already logged in (secret URL is not advertised).
    if (adminToken()) {
      items.push({ href: ADMIN_UI, label: t("nav.dashboard") });
    }
    const langOpts = I18N.SUPPORTED.map(
      (lang) =>
        `<option value="${lang}" ${I18N.getLang() === lang ? "selected" : ""}>${I18N.LABELS[lang]}</option>`,
    ).join("");
    const linksHtml = items
      .map((i) => {
        const active =
          i.href === "#/"
            ? hash === "#/" || hash === ""
            : i.href === ADMIN_UI
              ? isAdminUiHash(hash)
              : hash.startsWith(i.href);
        return `<a href="${i.href}" class="${active ? "active" : ""}">${i.label}</a>`;
      })
      .join("");
    const theme = getTheme();
    const themeLabel = theme === "dark" ? t("theme.toLight") : t("theme.toDark");
    nav.innerHTML = `
      <button type="button" class="nav-toggle" id="nav-toggle" aria-label="Menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
      <div class="nav-drawer" id="nav-drawer">
        ${linksHtml}
        <button type="button" class="theme-toggle" id="theme-toggle" aria-label="${esc(themeLabel)}" title="${esc(themeLabel)}">
          <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z"/>
          </svg>
          <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="4"/>
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
          </svg>
        </button>
        <select id="lang-select" class="lang-select" aria-label="Language">${langOpts}</select>
        ${adminToken() ? `<button type="button" id="nav-logout">${t("nav.logout")}</button>` : ""}
      </div>`;
    const toggle = document.getElementById("nav-toggle");
    const drawer = document.getElementById("nav-drawer");
    if (toggle && drawer) {
      toggle.onclick = () => {
        const open = document.body.classList.toggle("nav-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      };
      drawer.querySelectorAll("a").forEach((a) => {
        a.addEventListener("click", () => {
          document.body.classList.remove("nav-open");
          toggle.setAttribute("aria-expanded", "false");
        });
      });
    }
    const themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
      themeBtn.onclick = () => {
        applyTheme(getTheme() === "dark" ? "light" : "dark");
        setNav();
      };
    }
    const langSelect = document.getElementById("lang-select");
    if (langSelect) {
      langSelect.onchange = () => {
        I18N.setLang(langSelect.value);
        document.body.classList.remove("nav-open");
        route();
      };
    }
    const logout = document.getElementById("nav-logout");
    if (logout) {
      logout.onclick = async () => {
        try {
          await api("/logout", { method: "POST", token: adminToken(), admin: true });
        } catch (_) {}
        localStorage.removeItem(S.adminToken);
        location.hash = `${ADMIN_UI}/login`;
        route();
      };
    }
  }

  async function api(path, { method = "GET", token, body, admin = false, timeoutMs = 45000 } = {}) {
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res;
    try {
      res = await fetch((admin ? ADMIN : API) + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
    } catch (err) {
      if (err && err.name === "AbortError") throw new Error(t("error.timeout"));
      throw new Error(t("error.network"));
    } finally {
      clearTimeout(timer);
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      const detail = data?.detail || res.statusText;
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function alertHtml(type, msg) {
    return msg ? `<div class="alert alert-${type}">${esc(msg)}</div>` : "";
  }

  async function copyText(text) {
    const value = String(text || "");
    if (!value) return false;
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (_e) {
      try {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(ta);
        return ok;
      } catch (_e2) {
        return false;
      }
    }
  }

  function setBusy(btn, busy, labelBusy, labelIdle) {
    if (!btn) return;
    btn.disabled = !!busy;
    if (busy) {
      btn.dataset.labelIdle = labelIdle || btn.textContent;
      btn.textContent = labelBusy || t("ui.working");
    } else {
      btn.textContent = labelIdle || btn.dataset.labelIdle || btn.textContent;
    }
  }

  const ICON_EYE =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/></svg>';
  const ICON_EYE_OFF =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M3.3 2 2 3.3l3.1 3.1C3.3 7.5 1.7 9.1 1 12c1.7 3.9 6 7 11 7 2.1 0 4.1-.5 5.8-1.4L20.7 22 22 20.7 3.3 2zM12 17c-3.6 0-6.7-2-8.3-5 .7-1.4 1.9-2.7 3.4-3.6l1.7 1.7A5 5 0 0 0 12 17zm0-10c.5 0 1 .1 1.5.2l1.7 1.7A5 5 0 0 0 9.9 14l-1.8-1.8C7.4 10.5 7 9.3 7 8a5 5 0 0 1 5-5c.9 0 1.7.2 2.5.6L16 5.1C14.8 4.4 13.5 4 12 4 9.4 4 7.1 5.1 5.5 6.8L4.1 5.4C6 3.9 8.8 3 12 3c5 0 9.3 3.1 11 7-.7 1.6-1.9 3-3.4 4l-1.5-1.5c1-1 1.7-2.1 2.2-3.5C18.7 7 15.6 5 12 5z"/></svg>';

  function passwordFieldInner(id, value, placeholder = "") {
    return `
      <div class="password-wrap">
        <input id="${esc(id)}" type="password" value="${esc(value)}" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false" />
        <button type="button" class="password-toggle" data-toggle-for="${esc(id)}" aria-label="${esc(t("ui.showKey"))}" title="${esc(t("ui.showKey"))}">${ICON_EYE}</button>
      </div>`;
  }

  function bindPasswordToggles(root = document) {
    root.querySelectorAll("[data-toggle-for]").forEach((btn) => {
      btn.onclick = () => {
        const input = document.getElementById(btn.dataset.toggleFor);
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.innerHTML = show ? ICON_EYE_OFF : ICON_EYE;
        btn.setAttribute("aria-label", show ? t("ui.hideKey") : t("ui.showKey"));
        btn.title = show ? t("ui.hideKey") : t("ui.showKey");
      };
    });
  }

  function route() {
    try {
      const hash = location.hash || "#/";
      document.body.classList.remove("nav-open");
      // Old public admin URLs → home (do not reveal admin)
      if (isLegacyAdminHash(hash)) {
        location.replace("#/");
        return;
      }
      // Leaked legacy slug
      if (hash === "#/mrdevdeptraivodich" || hash.startsWith("#/mrdevdeptraivodich/")) {
        location.replace("#/");
        return;
      }
      document.body.classList.toggle(
        "docs-mode",
        hash.startsWith("#/docs") || hash.includes("/api-docs"),
      );
      document.body.classList.toggle("usage-mode", hash.startsWith("#/usage"));
      setNav();
      if (hash === `${ADMIN_UI}/login` || hash.startsWith(`${ADMIN_UI}/login`)) {
        return renderAdminLogin();
      }
      if (hash === `${ADMIN_UI}/api-docs` || hash.startsWith(`${ADMIN_UI}/api-docs/`)) {
        if (!adminToken()) {
          location.hash = `${ADMIN_UI}/login`;
          return renderAdminLogin();
        }
        if (window.MrdevAdminDocs && typeof window.MrdevAdminDocs.render === "function") {
          return window.MrdevAdminDocs.render(app, {
            esc,
            t,
            adminUi: ADMIN_UI,
          });
        }
        app.innerHTML = `<div class="panel"><h2>${t("adminDocs.title")}</h2><p class="sub">${t("docs.missing")}</p></div>`;
        return;
      }
      if (isAdminUiHash(hash)) return renderAdminDashboard();
      if (hash.startsWith("#/user")) return renderUserRedeem();
      if (hash.startsWith("#/chat")) return renderChat();
      if (hash.startsWith("#/usage")) return renderUsage();
      if (hash.startsWith("#/about")) return renderAboutPage();
      if (hash.startsWith("#/rules")) return renderRulesPage();
      if (hash.startsWith("#/contact")) return renderContactPage();
      if (hash === "#/models" || hash.startsWith("#/models?")) {
        renderHome();
        requestAnimationFrame(() => {
          document.getElementById("models")?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        return;
      }
      if (hash.startsWith("#/docs")) {
        if (window.MrdevDocs && typeof window.MrdevDocs.render === "function") {
          return window.MrdevDocs.render(app, {
            esc,
            api,
            userKey: userKey(),
            t,
          });
        }
        app.innerHTML = `<div class="panel"><h2>${t("nav.docs")}</h2><p class="sub">${t("docs.missing")}</p></div>`;
        return;
      }
      return renderHome();
    } catch (err) {
      console.error(err);
      if (window.__mrdevBootError) window.__mrdevBootError(err);
      app.innerHTML = `<div class="panel"><h2>${t("ui.error")}</h2><p class="sub">${esc(err.message || err)}</p></div>`;
    }
  }

  function siteFooterHtml() {
    return `
      <footer class="home-footer">
        <div class="home-footer-brand">
          <strong>MRDEV Gateway</strong>
          <span>${t("home.footer.tag")}</span>
        </div>
        <nav class="home-footer-nav" aria-label="Footer">
          <a href="#/">${t("nav.home")}</a>
          <a href="#/about">${t("home.footer.about")}</a>
          <a href="#/rules">${t("home.footer.rules")}</a>
          <a href="#/models">${t("home.footer.models")}</a>
          <a href="#/docs">${t("nav.docs")}</a>
          <a href="#/contact">${t("home.footer.contact")}</a>
          <a class="home-footer-tg-primary" href="https://t.me/kiro86bot" target="_blank" rel="noopener noreferrer">@kiro86bot</a>
          <a href="https://t.me/xapicombot" target="_blank" rel="noopener noreferrer">@xapicombot</a>
        </nav>
        <p class="home-footer-copy">${t("home.footer.copy")}</p>
      </footer>`;
  }

  function renderHome() {
    const models = [
      "claude-fable-5",
      "claude-opus-4-8",
      "claude-opus-4-7",
      "claude-opus-4-6",
      "claude-sonnet-5",
      "claude-sonnet-4-6",
      "claude-sonnet-4-5",
      "claude-haiku-4-5",
    ];
    const modelChips = models
      .map((m) => `<span class="home-chip mono">${esc(m)}</span>`)
      .join("");
    app.innerHTML = `
      <section class="home-hero">
        <div class="home-hero-bg" aria-hidden="true"></div>
        <div class="home-hero-inner">
          <p class="home-brand">${t("home.title")}</p>
          <h1 class="home-headline">${t("home.headline")}</h1>
          <p class="home-lead">${t("home.lead")}</p>
          <div class="home-cta">
            <a class="btn btn-primary" href="#/user">${t("home.cta.redeem")}</a>
            <a class="btn btn-secondary" href="#/docs">${t("home.cta.docs")}</a>
            <a class="btn btn-secondary" href="#/contact">${t("home.cta.contact")}</a>
          </div>
        </div>
      </section>

      <section class="home-section" id="architecture">
        <h2>${t("home.arch.title")}</h2>
        <p class="home-section-lead">${t("home.arch.lead")}</p>
        <div class="home-flow" role="list">
          <div class="home-flow-step" role="listitem">
            <span class="home-flow-n">01</span>
            <strong>${t("home.arch.s1.title")}</strong>
            <p>${t("home.arch.s1.desc")}</p>
          </div>
          <div class="home-flow-arrow" aria-hidden="true">→</div>
          <div class="home-flow-step" role="listitem">
            <span class="home-flow-n">02</span>
            <strong>${t("home.arch.s2.title")}</strong>
            <p>${t("home.arch.s2.desc")}</p>
          </div>
          <div class="home-flow-arrow" aria-hidden="true">→</div>
          <div class="home-flow-step" role="listitem">
            <span class="home-flow-n">03</span>
            <strong>${t("home.arch.s3.title")}</strong>
            <p>${t("home.arch.s3.desc")}</p>
          </div>
          <div class="home-flow-arrow" aria-hidden="true">→</div>
          <div class="home-flow-step" role="listitem">
            <span class="home-flow-n">04</span>
            <strong>${t("home.arch.s4.title")}</strong>
            <p>${t("home.arch.s4.desc")}</p>
          </div>
        </div>
      </section>

      <section class="home-section" id="models">
        <h2>${t("home.models.title")}</h2>
        <p class="home-section-lead">${t("home.models.lead")}</p>
        <div class="home-chips">${modelChips}</div>
        <p class="home-note">${t("home.models.note")} <a href="#/docs/models-list">${t("home.models.link")}</a></p>
      </section>

      ${siteFooterHtml()}`;
  }

  function renderAboutPage() {
    app.innerHTML = `
      <article class="site-page">
        <p class="site-crumb"><a href="#/">${t("nav.home")}</a> / ${t("home.about.title")}</p>
        <h1>${t("home.about.title")}</h1>
        <p class="home-section-lead">${t("home.about.lead")}</p>
        <ul class="home-list">
          <li>${t("home.about.li1")}</li>
          <li>${t("home.about.li2")}</li>
          <li>${t("home.about.li3")}</li>
          <li>${t("home.about.li4")}</li>
        </ul>
        <p class="site-page-links">
          <a href="#/rules">${t("home.footer.rules")}</a>
          <a href="#/contact">${t("home.footer.contact")}</a>
          <a href="#/docs">${t("nav.docs")}</a>
        </p>
      </article>
      ${siteFooterHtml()}`;
  }

  function renderRulesPage() {
    app.innerHTML = `
      <article class="site-page">
        <p class="site-crumb"><a href="#/">${t("nav.home")}</a> / ${t("home.rules.title")}</p>
        <h1>${t("home.rules.title")}</h1>
        <p class="home-section-lead">${t("home.rules.lead")}</p>
        <ol class="home-list numbered">
          <li>${t("home.rules.li1")}</li>
          <li>${t("home.rules.li2")}</li>
          <li>${t("home.rules.li3")}</li>
          <li>${t("home.rules.li4")}</li>
          <li>${t("home.rules.li5")}</li>
        </ol>
        <p class="site-page-links">
          <a href="#/about">${t("home.footer.about")}</a>
          <a href="#/contact">${t("home.footer.contact")}</a>
        </p>
      </article>
      ${siteFooterHtml()}`;
  }

  function renderContactPage() {
    app.innerHTML = `
      <article class="site-page">
        <p class="site-crumb"><a href="#/">${t("nav.home")}</a> / ${t("home.contact.title")}</p>
        <h1>${t("home.contact.title")}</h1>
        <p class="home-section-lead">${t("home.contact.lead")}</p>
        <div class="home-telegram-list">
          <a class="home-telegram home-telegram--featured" href="https://t.me/kiro86bot" target="_blank" rel="noopener noreferrer">
            <span class="home-telegram-icon" aria-hidden="true">TG</span>
            <span>
              <strong>${t("home.contact.primary")}</strong>
              <span class="mono">@kiro86bot</span>
            </span>
          </a>
          <a class="home-telegram home-telegram--secondary" href="https://t.me/xapicombot" target="_blank" rel="noopener noreferrer">
            <span class="home-telegram-icon" aria-hidden="true">TG</span>
            <span>
              <strong>Telegram</strong>
              <span class="mono">@xapicombot</span>
            </span>
          </a>
        </div>
        <p class="site-page-links">
          <a href="#/about">${t("home.footer.about")}</a>
          <a href="#/rules">${t("home.footer.rules")}</a>
          <a href="#/docs">${t("nav.docs")}</a>
        </p>
      </article>
      ${siteFooterHtml()}`;
  }

  function renderAdminLogin() {
    if (adminToken()) {
      location.hash = ADMIN_UI;
      return renderAdminDashboard();
    }
    app.innerHTML = `
      <section class="panel auth-shell">
        <h1>${t("login.title")}</h1>
        <p class="sub">${t("login.sub")}</p>
        <div id="alert"></div>
        <div class="field"><label>${t("login.username")}</label><input id="username" value="" autocomplete="username" /></div>
        <div class="field"><label>${t("login.password")}</label><input id="password" type="password" value="" autocomplete="current-password" /></div>
        <div class="field"><label>${t("login.otp")}</label><input id="otp" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="6" placeholder="000000" autocomplete="one-time-code" /></div>
        <p class="sub">${t("login.otpHintTotp")}</p>
        <button class="btn btn-primary btn-block" id="btn-login" type="button">${t("login.submit")}</button>
      </section>`;
    const alert = document.getElementById("alert");
    const btn = document.getElementById("btn-login");
    btn.onclick = async () => {
      const user = document.getElementById("username").value.trim();
      const pass = document.getElementById("password").value;
      const otp = document.getElementById("otp").value.trim();
      if (!user || !pass) {
        alert.innerHTML = alertHtml("warn", t("login.needBoth"));
        return;
      }
      if (otp && otp.length !== 6) {
        alert.innerHTML = alertHtml("warn", t("login.needOtp"));
        return;
      }
      setBusy(btn, true, t("login.working"), t("login.submit"));
      alert.innerHTML = alertHtml("warn", t("login.working"));
      try {
        const data = await api("/login", {
          method: "POST",
          admin: true,
          body: { username: user, password: pass, otp },
          timeoutMs: 30000,
        });
        localStorage.setItem(S.adminToken, data.access_token);
        alert.innerHTML = alertHtml("ok", t("login.ok"));
        setTimeout(() => {
          location.hash = ADMIN_UI;
          route();
        }, 250);
      } catch (err) {
        alert.innerHTML = alertHtml("error", err.message);
        setBusy(btn, false, null, t("login.submit"));
      }
    };
    ["password", "otp"].forEach((id) => {
      document.getElementById(id).addEventListener("keydown", (e) => {
        if (e.key === "Enter") btn.click();
      });
    });
  }

  async function renderAdminDashboard() {
    if (!adminToken()) {
      location.hash = `${ADMIN_UI}/login`;
      return renderAdminLogin();
    }
    app.innerHTML = `
      <section class="panel">
        <h1>${t("admin.title")}</h1>
        <p class="sub">${t("admin.sub")} · <a href="${ADMIN_UI}/api-docs">${t("admin.tab.apiDocs")}</a></p>
        <div id="alert"></div>
        <div class="stats" id="stats"></div>
        <div class="tabs">
          <button class="tab active" data-tab="cdks" type="button">${t("admin.tab.cdks")}</button>
          <button class="tab" data-tab="keys" type="button">${t("admin.tab.keys")}</button>
          <button class="tab" data-tab="aws" type="button">${t("admin.tab.aws")}</button>
          <button class="tab" data-tab="usage" type="button">${t("admin.tab.usage")}</button>
          <button class="tab" data-tab="logs" type="button">${t("admin.tab.logs")}</button>
        </div>
        <div id="tab-body"></div>
      </section>
      <div id="modal"></div>`;

    const alert = document.getElementById("alert");
    let tab = "cdks";
    let keys = [];
    let cdks = [];
    let awsCreds = [];
    let availableModels = [];
    let modelsLoading = null;
    let searchQuery = "";
    let tierFilter = ""; // "", "claude-opus-4-6", "claude-opus-4-8", "claude-fable-5", "__unlimited__"
    let searchTimer = null;
    let usagePeriod = "day";
    let usageDay = new Date().toISOString().slice(0, 10);
    let usageFrom = usageDay;
    let usageTo = usageDay;
    let usageReport = null;
    const CDK_PAGE_SIZE = 100;
    let cdkPage = 1;
    const LOG_PAGE_SIZE = 50;
    let logPage = 1;
    let logTotal = 0;
    let logFilters = { ip: "", method: "", status: "", path: "", errorsOnly: false };
    let logIpSummary = [];

    const matchesQuery = (parts) => {
      const q = searchQuery.trim().toLowerCase();
      if (!q) return true;
      return parts.some((p) => String(p || "").toLowerCase().includes(q));
    };

    const matchesTierFilter = (allowed) => {
      if (!tierFilter) return true;
      const tier = detectTier(allowed);
      if (tierFilter === "__unlimited__") return tier === "";
      return tier === tierFilter;
    };

    function tierFilterSelectHtml() {
      const opts = [
        ["", t("admin.filterTierAll")],
        ["claude-opus-4-6", t("admin.filterTier.46")],
        ["claude-opus-4-8", t("admin.filterTier.48")],
        ["claude-fable-5", t("admin.filterTier.fable5")],
        ["__unlimited__", t("admin.filterTier.unlimited")],
      ]
        .map(
          ([value, label]) =>
            `<option value="${esc(value)}" ${tierFilter === value ? "selected" : ""}>${esc(label)}</option>`,
        )
        .join("");
      return `<select class="tier-filter" id="admin-tier-filter" title="${esc(t("admin.filterTier"))}" aria-label="${esc(t("admin.filterTier"))}">${opts}</select>`;
    }

    const MODEL_CATALOG = [
      "claude-fable-5",
      "claude-opus-4-8",
      "claude-opus-4-7",
      "claude-opus-4-6",
      "claude-sonnet-5",
      "claude-sonnet-4-6",
      "claude-sonnet-4-5",
      "claude-haiku-4-5",
      "claude-opus-4-1",
      "claude-opus-4",
      "claude-sonnet-4",
      "claude-3-7-sonnet",
      "claude-3-5-sonnet",
      "claude-3-5-haiku",
      "claude-3-opus",
      "claude-3-sonnet",
      "claude-3-haiku",
    ];

    // Access ceilings for API keys / CDKs (pick one → full access up to that tier).
    const MODEL_TIERS = [
      { id: "claude-opus-4-6", labelKey: "admin.tier.46" },
      { id: "claude-opus-4-8", labelKey: "admin.tier.48" },
      { id: "claude-fable-5", labelKey: "admin.tier.fable5" },
    ];

    function mergeModelCatalog(list) {
      return Array.from(new Set([...(Array.isArray(list) ? list : []), ...MODEL_CATALOG])).sort((a, b) =>
        a.localeCompare(b),
      );
    }

    function detectTier(allowed) {
      const list = Array.isArray(allowed) ? allowed : [];
      if (!list.length) return "";
      for (const tier of [...MODEL_TIERS].reverse()) {
        if (list.some((m) => String(m) === tier.id || String(m).endsWith(tier.id))) return tier.id;
      }
      return null; // legacy exact list
    }

    function formatAllowedModels(allowed) {
      const tier = detectTier(allowed);
      if (tier === "") return t("admin.allModels");
      if (tier) {
        const meta = MODEL_TIERS.find((x) => x.id === tier);
        return meta ? t(meta.labelKey) : tier;
      }
      const n = (allowed || []).length;
      return n ? t("admin.nModels", { n }) : t("admin.allModels");
    }

    async function ensureModels() {
      if (availableModels.length > 1) return availableModels;
      if (modelsLoading) return modelsLoading;
      modelsLoading = api("/models", { admin: true, token: adminToken() })
        .then((list) => {
          availableModels = mergeModelCatalog(list);
          return availableModels;
        })
        .catch(() => {
          availableModels = mergeModelCatalog([]);
          return availableModels;
        })
        .finally(() => {
          modelsLoading = null;
        });
      return modelsLoading;
    }

    function modelPickerHtml(selected = []) {
      const sel = new Set(selected || []);
      const options = availableModels.length
        ? availableModels
            .map(
              (m) =>
                `<label class="model-opt"><input type="checkbox" class="m-model" value="${esc(m)}" ${sel.has(m) ? "checked" : ""} /> <span class="mono">${esc(m)}</span></label>`,
            )
            .join("")
        : `<p class="sub">${t("admin.modelsFail")}</p>`;
      return `
        <div class="field">
          <label>${t("admin.modelLimit")} <span class="sub">${t("admin.modelLimitHint")}</span></label>
          <input id="m-model-search" placeholder="${t("admin.filterModel")}" />
          <div class="model-list" id="m-model-list">${options}</div>
        </div>`;
    }

    function tierPickerHtml(selected) {
      const current = selected || "claude-opus-4-6";
      const options = [
        `<label class="model-opt"><input type="radio" name="m-tier" class="m-tier" value="" ${current === "" ? "checked" : ""} /> <span>${t("admin.tier.unlimited")}</span></label>`,
        ...MODEL_TIERS.map(
          (tier) =>
            `<label class="model-opt"><input type="radio" name="m-tier" class="m-tier" value="${esc(tier.id)}" ${current === tier.id ? "checked" : ""} /> <span><strong class="mono">${esc(tier.id)}</strong> — ${t(tier.labelKey)}</span></label>`,
        ),
      ].join("");
      return `
        <div class="field">
          <label>${t("admin.tierLimit")} <span class="sub">${t("admin.tierLimitHint")}</span></label>
          <div class="model-list" id="m-tier-list">${options}</div>
        </div>`;
    }

    function selectedTierModels() {
      const el = document.querySelector(".m-tier:checked");
      if (!el || !el.value) return [];
      return [el.value];
    }

    function bindDebouncedSearch(apply, { resetPage } = {}) {
      const searchEl = document.getElementById("admin-search");
      if (searchEl) {
        searchEl.oninput = () => {
          searchQuery = searchEl.value;
          if (typeof resetPage === "function") resetPage();
          clearTimeout(searchTimer);
          searchTimer = setTimeout(apply, 120);
        };
      }
      const tierEl = document.getElementById("admin-tier-filter");
      if (tierEl) {
        tierEl.onchange = () => {
          tierFilter = tierEl.value;
          if (typeof resetPage === "function") resetPage();
          apply();
        };
      }
    }

    function downloadTextFile(filename, text) {
      const blob = new Blob([text.endsWith("\n") ? text : text + "\n"], {
        type: "text/plain;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    function showCreatedCdks(created) {
      const codes = (created || []).map((c) => c.code).filter(Boolean);
      const text = codes.join("\n");
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const filename = `cdk-new-${stamp}.txt`;
      if (text) downloadTextFile(filename, text);
      showModal(`
        <h3>${t("admin.createdCdkTitle", { n: codes.length })}</h3>
        <p class="sub">${t("admin.createdCdkHint")}</p>
        <div class="field">
          <label>${t("admin.createdCdkList")}</label>
          <textarea id="m-cdk-new" class="mono cdk-new-ta" readonly rows="${Math.min(16, Math.max(6, codes.length + 1))}">${esc(text)}</textarea>
        </div>
        <div class="actions">
          <button class="btn btn-primary" id="m-cdk-copy" type="button">${t("admin.copyAll")}</button>
          <button class="btn btn-secondary" id="m-cdk-dl" type="button">${t("admin.downloadAgain")}</button>
          <button class="btn btn-secondary" id="m-cdk-close" type="button">${t("admin.close")}</button>
        </div>`);
      document.getElementById("m-cdk-close").onclick = closeModal;
      document.getElementById("m-cdk-copy").onclick = async () => {
        const ok = await copyText(text);
        setAlert("ok", ok ? t("admin.copiedBulkCdk", { n: codes.length }) : t("admin.copiedCdk"));
      };
      document.getElementById("m-cdk-dl").onclick = () => {
        downloadTextFile(filename, text);
        setAlert("ok", t("admin.downloadedBulkCdk", { n: codes.length }));
      };
      const ta = document.getElementById("m-cdk-new");
      if (ta) {
        ta.focus();
        ta.select();
      }
    }

    function bindModelPicker() {
      const search = document.getElementById("m-model-search");
      const list = document.getElementById("m-model-list");
      if (!search || !list) return;
      search.oninput = () => {
        const q = search.value.trim().toLowerCase();
        list.querySelectorAll(".model-opt").forEach((el) => {
          const v = el.textContent.toLowerCase();
          el.style.display = !q || v.includes(q) ? "" : "none";
        });
      };
    }

    function selectedModels() {
      return Array.from(document.querySelectorAll(".m-model:checked")).map((el) => el.value);
    }

    const setAlert = (type, msg) => {
      alert.innerHTML = alertHtml(type, msg);
    };

    document.querySelectorAll(".tab").forEach((btn) => {
      btn.onclick = () => {
        tab = btn.dataset.tab;
        document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
        paint();
        if (tab === "usage") loadUsageReport();
        if (tab === "logs") loadRequestLogs({ resetPage: true });
      };
    });

    function showModal(html) {
      document.getElementById("modal").innerHTML = `<div class="modal-backdrop"><div class="modal">${html}</div></div>`;
    }
    function closeModal() {
      document.getElementById("modal").innerHTML = "";
    }

    function paintStats() {
      const available = cdks.filter((c) => c.status === "available").length;
      const redeemed = cdks.filter((c) => c.status === "redeemed").length;
      const activeKeys = keys.filter((k) => !k.revoked).length;
      const awsOn = awsCreds.filter((c) => c.enabled).length;
      const tokens = keys.reduce((s, k) => s + (k.total_tokens_month || 0), 0);
      document.getElementById("stats").innerHTML = `
        <div class="stat"><div class="n">${available}</div><div class="l">${t("admin.stat.cdkLeft")}</div></div>
        <div class="stat"><div class="n">${redeemed}</div><div class="l">${t("admin.stat.cdkRedeemed")}</div></div>
        <div class="stat"><div class="n">${activeKeys}</div><div class="l">${t("admin.stat.activeKeys")}</div></div>
        <div class="stat"><div class="n">${awsOn}</div><div class="l">${t("admin.stat.awsKeys")}</div></div>
        <div class="stat"><div class="n">${num(tokens)}</div><div class="l">${t("admin.stat.tokensMonth")}</div></div>`;
    }

    function bindBulkSelect(kind) {
      const selectAll = document.getElementById("select-all");
      const bulkBtn = document.getElementById("btn-bulk-delete");
      const copyBtn = document.getElementById("btn-bulk-copy");
      const dlBtn = document.getElementById("btn-bulk-download");
      const countEl = document.getElementById("bulk-count");
      const boxes = () => Array.from(document.querySelectorAll(".row-check"));
      const selectedIds = () => boxes().filter((b) => b.checked).map((b) => b.value);
      const sync = () => {
        const all = boxes();
        const checked = all.filter((b) => b.checked);
        if (selectAll) {
          selectAll.checked = all.length > 0 && checked.length === all.length;
          selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
        }
        const empty = checked.length === 0;
        if (bulkBtn) bulkBtn.disabled = empty;
        if (copyBtn) copyBtn.disabled = empty;
        if (dlBtn) dlBtn.disabled = empty;
        if (countEl) countEl.textContent = checked.length ? t("admin.selected", { n: checked.length }) : "";
      };
      if (selectAll) {
        selectAll.onchange = () => {
          boxes().forEach((b) => {
            b.checked = selectAll.checked;
          });
          sync();
        };
      }
      boxes().forEach((b) => {
        b.onchange = sync;
      });
      if (copyBtn && kind === "cdk") {
        copyBtn.onclick = async () => {
          const ids = selectedIds();
          if (!ids.length) return;
          const text = ids.join("\n");
          try {
            await navigator.clipboard.writeText(text);
            setAlert("ok", t("admin.copiedBulkCdk", { n: ids.length }));
          } catch (_err) {
            // Fallback for older browsers / insecure context
            const ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
            setAlert("ok", t("admin.copiedBulkCdk", { n: ids.length }));
          }
        };
      }
      if (dlBtn && kind === "cdk") {
        dlBtn.onclick = () => {
          const ids = selectedIds();
          if (!ids.length) return;
          const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
          downloadTextFile(`cdk-${stamp}.txt`, ids.join("\n"));
          setAlert("ok", t("admin.downloadedBulkCdk", { n: ids.length }));
        };
      }
      if (bulkBtn) {
        bulkBtn.onclick = async () => {
          const ids = selectedIds();
          if (!ids.length) return;
          const label = kind === "cdk" ? "CDK" : "API key";
          if (!confirm(t("admin.confirmBulk", { n: ids.length, label }) + (kind === "key" ? t("admin.confirmBulkKeyExtra") : ""))) return;
          bulkBtn.disabled = true;
          let ok = 0;
          let fail = 0;
          for (const id of ids) {
            try {
              if (kind === "cdk") {
                await api(`/cdks/${encodeURIComponent(id)}/hard`, {
                  method: "DELETE",
                  admin: true,
                  token: adminToken(),
                });
              } else {
                await api(`/keys/${id}/hard`, {
                  method: "DELETE",
                  admin: true,
                  token: adminToken(),
                });
              }
              ok += 1;
            } catch (_err) {
              fail += 1;
            }
          }
          setAlert(fail ? "warn" : "ok", fail ? t("admin.deletedNFail", { ok, fail }) : t("admin.deletedN", { ok }));
          await load();
        };
      }
      sync();
    }

    function renderCdkPager(filteredCount) {
      const pager = document.getElementById("cdk-pager");
      if (!pager) return;
      const totalPages = Math.max(1, Math.ceil(filteredCount / CDK_PAGE_SIZE));
      if (cdkPage > totalPages) cdkPage = totalPages;
      if (filteredCount <= CDK_PAGE_SIZE) {
        pager.hidden = true;
        pager.innerHTML = "";
        return;
      }
      pager.hidden = false;
      const windowSize = 5;
      let start = Math.max(1, cdkPage - Math.floor(windowSize / 2));
      let end = Math.min(totalPages, start + windowSize - 1);
      start = Math.max(1, end - windowSize + 1);
      const pages = [];
      for (let p = start; p <= end; p += 1) pages.push(p);
      pager.innerHTML = `
        <button type="button" class="pager-btn" data-page="prev" ${cdkPage <= 1 ? "disabled" : ""}>${t("usage.prev")}</button>
        ${start > 1 ? `<button type="button" class="pager-btn" data-page="1">1</button>${start > 2 ? `<span class="pager-ellipsis">…</span>` : ""}` : ""}
        ${pages
          .map((p) => `<button type="button" class="pager-btn ${p === cdkPage ? "active" : ""}" data-page="${p}">${p}</button>`)
          .join("")}
        ${end < totalPages ? `${end < totalPages - 1 ? `<span class="pager-ellipsis">…</span>` : ""}<button type="button" class="pager-btn" data-page="${totalPages}">${totalPages}</button>` : ""}
        <button type="button" class="pager-btn" data-page="next" ${cdkPage >= totalPages ? "disabled" : ""}>${t("usage.next")}</button>
        <span class="pager-meta">${t("usage.pageOf", { page: cdkPage, pages: totalPages })}</span>`;
      pager.querySelectorAll("[data-page]").forEach((btn) => {
        btn.onclick = () => {
          const raw = btn.getAttribute("data-page");
          const total = Math.max(1, Math.ceil(filteredCount / CDK_PAGE_SIZE));
          let next = cdkPage;
          if (raw === "prev") next = Math.max(1, cdkPage - 1);
          else if (raw === "next") next = Math.min(total, cdkPage + 1);
          else next = Number(raw) || 1;
          if (next === cdkPage) return;
          cdkPage = next;
          fillCdkRows();
        };
      });
    }

    function filterNoMatchLabel() {
      const q = searchQuery.trim();
      if (q) return t("admin.noMatch", { q: esc(q) });
      if (tierFilter) return t("admin.noMatchTier");
      return t("admin.noMatch", { q: "" });
    }

    function fillCdkRows() {
      const filtered = cdks.filter(
        (c) => matchesQuery([c.code, c.label, c.key_id, c.status]) && matchesTierFilter(c.allowed_models),
      );
      const totalPages = Math.max(1, Math.ceil(filtered.length / CDK_PAGE_SIZE));
      if (cdkPage > totalPages) cdkPage = totalPages;
      const offset = (cdkPage - 1) * CDK_PAGE_SIZE;
      const pageRows = filtered.slice(offset, offset + CDK_PAGE_SIZE);
      const from = filtered.length ? offset + 1 : 0;
      const to = offset + pageRows.length;
      const meta = document.querySelector("#tab-body .toolbar-meta");
      if (meta) {
        meta.textContent = filtered.length
          ? `${t("admin.cdkMeta", { a: filtered.length, b: cdks.length })} · ${t("usage.pageRange", { from, to, total: filtered.length })}`
          : t("admin.cdkMeta", { a: 0, b: cdks.length });
      }
      const tbody = document.getElementById("tbody");
      if (!tbody) return;
      if (!cdks.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty">${t("admin.noCdk")}</td></tr>`;
      } else if (!filtered.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty">${filterNoMatchLabel()}</td></tr>`;
      } else {
        tbody.innerHTML = pageRows
          .map((c) => {
            const badge =
              c.status === "available"
                ? "badge-ok"
                : c.status === "redeemed"
                  ? "badge-muted"
                  : "badge-off";
            return `<tr>
              <td class="col-check"><input type="checkbox" class="row-check" value="${esc(c.code)}" /></td>
              <td class="mono">${esc(c.code)}</td>
              <td>${esc(c.label)}</td>
              <td class="mono">${esc(c.key_id || "—")}</td>
              <td>${num(c.rpm_limit)} rpm · ${c.monthly_token_quota > 0 ? num(c.monthly_token_quota) : "∞"} tok<div style="color:var(--muted);font-size:0.72rem" title="${esc((c.allowed_models || []).join(", "))}">${esc(formatAllowedModels(c.allowed_models))}</div></td>
              <td><span class="badge ${badge}">${esc(c.status)}</span></td>
              <td class="actions">
                ${c.status === "available" ? `<button class="btn btn-secondary btn-small" data-copy="${esc(c.code)}" type="button">${t("admin.copy")}</button>
                <button class="btn btn-danger btn-small" data-revoke-cdk="${esc(c.code)}" type="button">${t("admin.revoke")}</button>` : ""}
                <button class="btn btn-danger btn-small" data-delete-cdk="${esc(c.code)}" type="button">${t("admin.delete")}</button>
              </td>
            </tr>`;
          })
          .join("");
      }
      renderCdkPager(filtered.length);
      bindBulkSelect("cdk");
      tbody.querySelectorAll("[data-copy]").forEach((btn) => {
        btn.onclick = async () => {
          await navigator.clipboard.writeText(btn.dataset.copy);
          setAlert("ok", t("admin.copiedCdk"));
        };
      });
      tbody.querySelectorAll("[data-revoke-cdk]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm(t("admin.confirmRevokeCdk"))) return;
          try {
            await api(`/cdks/${encodeURIComponent(btn.dataset.revokeCdk)}`, {
              method: "DELETE",
              admin: true,
              token: adminToken(),
            });
            setAlert("ok", t("admin.revokedCdk"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
      tbody.querySelectorAll("[data-delete-cdk]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm(t("admin.confirmDeleteCdk"))) return;
          try {
            await api(`/cdks/${encodeURIComponent(btn.dataset.deleteCdk)}/hard`, {
              method: "DELETE",
              admin: true,
              token: adminToken(),
            });
            setAlert("ok", t("admin.deletedCdk"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
    }

    async function openCreateCdkModal() {
      showModal(`
        <h3>${t("admin.createCdk")}</h3>
        <div class="field"><label>${t("admin.label")}</label><input id="m-label" value="user" /></div>
        <div class="row">
          <div class="field"><label>${t("admin.count")}</label><input id="m-count" type="number" min="1" max="1000" value="1" /></div>
          <div class="field"><label>${t("admin.rpm")}</label><input id="m-rpm" type="number" min="0" value="60" /></div>
          <div class="field"><label>${t("admin.quota")}</label><input id="m-quota" type="number" min="0" value="2000000" /></div>
        </div>
        ${tierPickerHtml("claude-opus-4-6")}
        <div class="actions">
          <button class="btn btn-primary" id="m-save" type="button">${t("admin.create")}</button>
          <button class="btn btn-secondary" id="m-cancel" type="button">${t("admin.cancel")}</button>
        </div>`);
      document.getElementById("m-cancel").onclick = closeModal;
      document.getElementById("m-save").onclick = async () => {
        const saveBtn = document.getElementById("m-save");
        if (saveBtn) saveBtn.disabled = true;
        try {
          const created = await api("/cdks", {
            method: "POST",
            admin: true,
            token: adminToken(),
            body: {
              label: document.getElementById("m-label").value.trim() || "user",
              count: Number(document.getElementById("m-count").value || 1),
              rpm_limit: Number(document.getElementById("m-rpm").value),
              monthly_token_quota: Number(document.getElementById("m-quota").value),
              allowed_models: selectedTierModels(),
            },
          });
          setAlert("ok", t("admin.createdCdk", { n: created.length }));
          cdkPage = 1;
          await load();
          showCreatedCdks(created);
        } catch (err) {
          if (saveBtn) saveBtn.disabled = false;
          setAlert("error", err.message);
        }
      };
    }

    function paintCdks() {
      document.getElementById("tab-body").innerHTML = `
        <div class="toolbar">
          <button class="btn btn-primary" id="btn-new-cdk" type="button">${t("admin.createCdk")}</button>
          <input class="search-input" id="admin-search" type="search" placeholder="${t("admin.searchCdk")}" value="${esc(searchQuery)}" />
          ${tierFilterSelectHtml()}
          <button class="btn btn-secondary btn-small" id="btn-bulk-copy" type="button" disabled>${t("admin.copySelected")}</button>
          <button class="btn btn-secondary btn-small" id="btn-bulk-download" type="button" disabled>${t("admin.downloadSelected")}</button>
          <button class="btn btn-danger btn-small" id="btn-bulk-delete" type="button" disabled>${t("admin.deleteSelected")}</button>
          <span class="sub" id="bulk-count"></span>
          <button class="btn btn-secondary btn-small" id="btn-refresh" type="button">${t("admin.refresh")}</button>
        </div>
        <p class="sub toolbar-meta">${t("admin.cdkMeta", { a: 0, b: cdks.length })}</p>
        <div style="overflow:auto">
          <table class="data">
            <thead><tr>
              <th class="col-check"><input type="checkbox" id="select-all" title="${t("admin.selectAll")}" /></th>
              <th>${t("admin.code")}</th><th>${t("admin.label")}</th><th>${t("admin.key")}</th><th>${t("admin.limits")}</th><th>${t("admin.status")}</th><th></th>
            </tr></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
        <nav class="pager" id="cdk-pager" hidden></nav>`;
      bindDebouncedSearch(fillCdkRows, { resetPage: () => { cdkPage = 1; } });
      document.getElementById("btn-new-cdk").onclick = openCreateCdkModal;
      document.getElementById("btn-refresh").onclick = load;
      fillCdkRows();
    }

    function fillKeyRows() {
      const filtered = keys.filter(
        (k) => matchesQuery([k.name, k.key_id]) && matchesTierFilter(k.allowed_models),
      );
      const meta = document.querySelector("#tab-body .toolbar-meta");
      if (meta) meta.textContent = t("admin.keyMeta", { a: filtered.length, b: keys.length });
      const tbody = document.getElementById("tbody");
      if (!tbody) return;
      if (!keys.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty">${t("admin.noKey")}</td></tr>`;
      } else if (!filtered.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty">${filterNoMatchLabel()}</td></tr>`;
      } else {
        tbody.innerHTML = filtered
          .map((k) => {
            const quota = k.monthly_token_quota > 0 ? num(k.monthly_token_quota) : "∞";
            return `<tr>
              <td class="col-check"><input type="checkbox" class="row-check" value="${esc(k.key_id)}" /></td>
              <td><strong>${esc(k.name)}</strong></td>
              <td class="mono">${esc(k.key_id)}</td>
              <td>${num(k.total_tokens_month)} / ${quota}<div style="color:var(--muted);font-size:0.75rem">${num(k.request_count_month)} req</div></td>
              <td>${num(k.rpm_limit)} rpm<div style="color:var(--muted);font-size:0.72rem" title="${esc((k.allowed_models || []).join(", "))}">${esc(formatAllowedModels(k.allowed_models))}</div></td>
              <td>${k.revoked ? '<span class="badge badge-off">revoked</span>' : '<span class="badge badge-ok">active</span>'}</td>
              <td class="actions">
                ${k.revoked ? "" : `<button class="btn btn-danger btn-small" data-revoke="${esc(k.key_id)}" type="button">${t("admin.revoke")}</button>`}
                <button class="btn btn-danger btn-small" data-delete="${esc(k.key_id)}" type="button">${t("admin.delete")}</button>
              </td>
            </tr>`;
          })
          .join("");
      }
      bindBulkSelect("key");
      tbody.querySelectorAll("[data-revoke]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm(t("admin.confirmRevokeKey"))) return;
          try {
            await api(`/keys/${btn.dataset.revoke}`, { method: "DELETE", admin: true, token: adminToken() });
            setAlert("ok", t("admin.revokedKey"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
      tbody.querySelectorAll("[data-delete]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm(t("admin.confirmDeleteKey"))) return;
          try {
            await api(`/keys/${btn.dataset.delete}/hard`, {
              method: "DELETE",
              admin: true,
              token: adminToken(),
            });
            setAlert("ok", t("admin.deletedKey"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
    }

    async function openCreateKeyModal() {
      showModal(`
        <h3>${t("admin.createKey")}</h3>
        <div class="field"><label>${t("admin.name")}</label><input id="m-name" value="direct" /></div>
        <div class="row">
          <div class="field"><label>${t("admin.rpm")}</label><input id="m-rpm" type="number" min="0" value="60" /></div>
          <div class="field"><label>${t("admin.quota")}</label><input id="m-quota" type="number" min="0" value="2000000" /></div>
        </div>
        ${tierPickerHtml("claude-opus-4-6")}
        <div class="actions">
          <button class="btn btn-primary" id="m-save" type="button">${t("admin.create")}</button>
          <button class="btn btn-secondary" id="m-cancel" type="button">${t("admin.cancel")}</button>
        </div>`);
      document.getElementById("m-cancel").onclick = closeModal;
      document.getElementById("m-save").onclick = async () => {
        try {
          const created = await api("/keys", {
            method: "POST",
            admin: true,
            token: adminToken(),
            body: {
              name: document.getElementById("m-name").value.trim() || "direct",
              rpm_limit: Number(document.getElementById("m-rpm").value),
              monthly_token_quota: Number(document.getElementById("m-quota").value),
              allowed_models: selectedTierModels(),
            },
          });
          showModal(`
            <h3>${t("admin.keyCreated")}</h3>
            <p class="sub">${t("admin.keyOnce")}</p>
            <div class="key-reveal mono" id="revealed">${esc(created.api_key)}</div>
            <div class="actions">
              <button class="btn btn-primary" id="m-copy" type="button">${t("admin.copy")}</button>
              <button class="btn btn-secondary" id="m-close" type="button">${t("admin.close")}</button>
            </div>`);
          document.getElementById("m-copy").onclick = async () => {
            await navigator.clipboard.writeText(created.api_key);
            setAlert("ok", t("admin.copiedKey"));
          };
          document.getElementById("m-close").onclick = async () => {
            closeModal();
            await load();
          };
        } catch (err) {
          setAlert("error", err.message);
        }
      };
    }

    function paintKeys() {
      const includeRevoked = document.getElementById("inc-revoked")?.checked || false;
      document.getElementById("tab-body").innerHTML = `
        <div class="toolbar">
          <button class="btn btn-primary" id="btn-new-key" type="button">${t("admin.createKey")}</button>
          <input class="search-input" id="admin-search" type="search" placeholder="${t("admin.searchKey")}" value="${esc(searchQuery)}" />
          ${tierFilterSelectHtml()}
          <button class="btn btn-danger btn-small" id="btn-bulk-delete" type="button" disabled>${t("admin.deleteSelected")}</button>
          <span class="sub" id="bulk-count"></span>
          <label style="display:flex;gap:0.4rem;align-items:center;color:var(--muted);font-size:0.9rem">
            <input type="checkbox" id="inc-revoked" ${includeRevoked ? "checked" : ""} /> ${t("admin.showRevoked")}
          </label>
          <button class="btn btn-secondary btn-small" id="btn-refresh" type="button">${t("admin.refresh")}</button>
        </div>
        <p class="sub toolbar-meta">${t("admin.keyMeta", { a: 0, b: keys.length })}</p>
        <div style="overflow:auto">
          <table class="data">
            <thead><tr>
              <th class="col-check"><input type="checkbox" id="select-all" title="${t("admin.selectAll")}" /></th>
              <th>${t("admin.name")}</th><th>${t("admin.keyId")}</th><th>${t("admin.usageCol")}</th><th>${t("admin.limits")}</th><th>${t("admin.status")}</th><th></th>
            </tr></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>`;
      bindDebouncedSearch(fillKeyRows);
      document.getElementById("btn-new-key").onclick = openCreateKeyModal;
      document.getElementById("inc-revoked").onchange = load;
      document.getElementById("btn-refresh").onclick = load;
      fillKeyRows();
    }

    function paintUsage() {
      document.getElementById("tab-body").innerHTML = `
        <div class="toolbar usage-filter-bar">
          <select id="usage-period">
            <option value="day" ${usagePeriod === "day" ? "selected" : ""}>${t("admin.period.day")}</option>
            <option value="week" ${usagePeriod === "week" ? "selected" : ""}>${t("admin.period.week")}</option>
            <option value="month" ${usagePeriod === "month" ? "selected" : ""}>${t("admin.period.month")}</option>
            <option value="custom" ${usagePeriod === "custom" ? "selected" : ""}>${t("admin.period.custom")}</option>
          </select>
          <input type="date" id="usage-day" value="${esc(usageDay)}" ${usagePeriod === "custom" ? "hidden" : ""} />
          <input type="date" id="usage-from" value="${esc(usageFrom)}" ${usagePeriod === "custom" ? "" : "hidden"} />
          <span class="sub" id="usage-to-label" ${usagePeriod === "custom" ? "" : "hidden"}>→</span>
          <input type="date" id="usage-to" value="${esc(usageTo)}" ${usagePeriod === "custom" ? "" : "hidden"} />
          <button class="btn btn-primary btn-small" id="usage-apply" type="button">${t("admin.view")}</button>
          <button class="btn btn-secondary btn-small" id="btn-refresh" type="button">${t("admin.refresh")}</button>
        </div>
        <div class="stats usage-stats" id="usage-summary-stats">
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.totalTokens")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.input")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.output")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.cacheRW")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.requests")}</div></div>
        </div>
        <p class="sub" id="usage-range-label"></p>
        <div class="usage-admin-grid">
          <div>
            <h3 class="usage-section-title">${t("admin.byDay")}</h3>
            <div class="usage-table-wrap">
              <table class="data">
                <thead><tr><th>${t("admin.col.day")}</th><th>${t("stat.input")}</th><th>${t("stat.output")}</th><th>${t("stat.cacheRW")}</th><th>${t("stat.totalTokens")}</th><th>${t("stat.requests")}</th></tr></thead>
                <tbody id="usage-bucket-rows"><tr><td colspan="6" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 class="usage-section-title">${t("admin.byUser")}</h3>
            <div class="usage-table-wrap">
              <table class="data">
                <thead><tr><th>${t("admin.col.user")}</th><th>${t("admin.keyId")}</th><th>${t("stat.totalTokens")}</th><th>${t("stat.requests")}</th><th></th></tr></thead>
                <tbody id="usage-key-rows"><tr><td colspan="5" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
          </div>
        </div>`;

      const periodEl = document.getElementById("usage-period");
      const dayEl = document.getElementById("usage-day");
      const fromEl = document.getElementById("usage-from");
      const toEl = document.getElementById("usage-to");
      const toLabel = document.getElementById("usage-to-label");
      const syncPeriodUi = () => {
        const custom = periodEl.value === "custom";
        dayEl.hidden = custom;
        fromEl.hidden = !custom;
        toEl.hidden = !custom;
        toLabel.hidden = !custom;
      };
      periodEl.onchange = syncPeriodUi;
      document.getElementById("usage-apply").onclick = async () => {
        usagePeriod = periodEl.value;
        usageDay = dayEl.value || usageDay;
        usageFrom = fromEl.value || usageFrom;
        usageTo = toEl.value || usageTo;
        await loadUsageReport();
      };
      document.getElementById("btn-refresh").onclick = loadUsageReport;
      renderUsageReport();
    }

    function renderUsageReport() {
      if (!usageReport) {
        document.getElementById("usage-bucket-rows").innerHTML =
          `<tr><td colspan="6" class="empty">${t("admin.pickRange")}</td></tr>`;
        document.getElementById("usage-key-rows").innerHTML =
          `<tr><td colspan="5" class="empty">${t("admin.pickRange")}</td></tr>`;
        return;
      }
      const r = usageReport;
      document.getElementById("usage-summary-stats").innerHTML = `
        <div class="stat"><div class="n">${num(r.total_tokens)}</div><div class="l">${t("stat.totalTokens")}</div></div>
        <div class="stat"><div class="n">${num(r.prompt_tokens)}</div><div class="l">${t("stat.input")}</div></div>
        <div class="stat"><div class="n">${num(r.completion_tokens)}</div><div class="l">${t("stat.output")}</div></div>
        <div class="stat"><div class="n">${num(r.cache_read_tokens)} / ${num(r.cache_write_tokens)}</div><div class="l">${t("stat.cacheRW")}</div></div>
        <div class="stat"><div class="n">${num(r.request_count)}</div><div class="l">${t("stat.requests")}</div></div>`;
      document.getElementById("usage-range-label").textContent =
        t("admin.rangeLabel", { from: r.date_from, to: r.date_to });

      const buckets = r.buckets || [];
      document.getElementById("usage-bucket-rows").innerHTML = buckets.length
        ? buckets
            .map(
              (b) => `<tr>
                <td>${esc(b.label)}</td>
                <td>${num(b.prompt_tokens)}</td>
                <td>${num(b.completion_tokens)}</td>
                <td>${num(b.cache_read_tokens)} / ${num(b.cache_write_tokens)}</td>
                <td><strong>${num(b.total_tokens)}</strong></td>
                <td>${num(b.request_count)}</td>
              </tr>`,
            )
            .join("")
        : `<tr><td colspan="6" class="empty">${t("admin.noUsage")}</td></tr>`;

      const byKey = r.by_key || [];
      document.getElementById("usage-key-rows").innerHTML = byKey.length
        ? byKey
            .map(
              (k) => `<tr>
                <td><strong>${esc(k.key_name)}</strong></td>
                <td class="mono">${esc(k.key_id)}</td>
                <td><strong>${num(k.total_tokens)}</strong>
                  <div style="color:var(--muted);font-size:0.72rem">${t("stat.input")} ${num(k.prompt_tokens)} · ${t("stat.output")} ${num(k.completion_tokens)}</div>
                </td>
                <td>${num(k.request_count)}</td>
                <td>${k.key_deleted ? '<span class="badge badge-off">deleted</span>' : '<span class="badge badge-ok">active</span>'}</td>
              </tr>`,
            )
            .join("")
        : `<tr><td colspan="5" class="empty">${t("admin.noUsage")}</td></tr>`;
    }

    async function loadUsageReport() {
      try {
        const params = new URLSearchParams({ period: usagePeriod });
        if (usagePeriod === "custom") {
          params.set("date_from", usageFrom);
          params.set("date_to", usageTo);
        } else {
          params.set("day", usageDay);
        }
        usageReport = await api(`/usage/summary?${params}`, {
          admin: true,
          token: adminToken(),
        });
        if (tab === "usage") renderUsageReport();
        setAlert("ok", t("admin.usageLoaded", { from: usageReport.date_from, to: usageReport.date_to }));
      } catch (err) {
        setAlert("error", err.message);
      }
    }

    async function openAwsModal(existing) {
      showModal(`<h3>${existing ? t("admin.aws.edit") : t("admin.aws.create")}</h3><p class="sub">${t("admin.loadingModels")}</p>`);
      await ensureModels();
      const prefer = [
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-opus-4-6",
      ];
      const selected = existing?.allowed_models?.length
        ? existing.allowed_models
        : prefer.filter((m) => availableModels.includes(m));
      showModal(`
        <h3>${existing ? t("admin.aws.edit") : t("admin.aws.create")}</h3>
        <p class="sub">${t("admin.aws.hint")}</p>
        <div class="field"><label>${t("admin.name")}</label><input id="m-name" value="${esc(existing?.name || "aws")}" /></div>
        <div class="field"><label>${t("admin.aws.accessKey")}</label><input id="m-ak" value="${esc(existing ? "" : "")}" placeholder="${existing ? existing.access_key_id_masked : "AKIA…"}" autocomplete="off" /></div>
        <div class="field"><label>${t("admin.aws.secretKey")}</label><input id="m-sk" type="password" value="" placeholder="${existing ? t("admin.aws.secretKeep") : ""}" autocomplete="new-password" /></div>
        <div class="field"><label>${t("admin.aws.sessionToken")} <span class="sub">${t("admin.aws.optional")}</span></label><input id="m-st" value="" autocomplete="off" /></div>
        <div class="row">
          <div class="field"><label>${t("admin.aws.region")}</label><input id="m-region" value="${esc(existing?.region || "")}" placeholder="us-west-2" /></div>
          <div class="field"><label>${t("admin.aws.priority")}</label><input id="m-priority" type="number" min="0" value="${esc(String(existing?.priority ?? 100))}" /></div>
        </div>
        ${modelPickerHtml(selected)}
        <div class="actions">
          <button class="btn btn-primary" id="m-save" type="button">${existing ? t("admin.aws.save") : t("admin.create")}</button>
          <button class="btn btn-secondary" id="m-cancel" type="button">${t("admin.cancel")}</button>
        </div>`);
      bindModelPicker();
      document.getElementById("m-cancel").onclick = closeModal;
      document.getElementById("m-save").onclick = async () => {
        const body = {
          name: document.getElementById("m-name").value.trim() || "aws",
          region: document.getElementById("m-region").value.trim(),
          priority: Number(document.getElementById("m-priority").value || 100),
          allowed_models: selectedModels(),
          session_token: document.getElementById("m-st").value.trim(),
        };
        const ak = document.getElementById("m-ak").value.trim();
        const sk = document.getElementById("m-sk").value.trim();
        try {
          if (existing) {
            if (ak) body.access_key_id = ak;
            if (sk) body.secret_access_key = sk;
            await api(`/aws-credentials/${existing.cred_id}`, {
              method: "PATCH",
              admin: true,
              token: adminToken(),
              body,
            });
            setAlert("ok", t("admin.aws.updated"));
          } else {
            if (!ak || !sk) {
              setAlert("error", t("admin.aws.needKeys"));
              return;
            }
            body.access_key_id = ak;
            body.secret_access_key = sk;
            body.enabled = true;
            await api("/aws-credentials", {
              method: "POST",
              admin: true,
              token: adminToken(),
              body,
            });
            setAlert("ok", t("admin.aws.created"));
          }
          closeModal();
          await load();
        } catch (err) {
          setAlert("error", err.message);
        }
      };
    }

    function paintAws() {
      const shortModel = (m) =>
        String(m || "")
          .replace(/^us\.anthropic\./, "")
          .replace(/^global\.anthropic\./, "")
          .replace(/^anthropic\./, "");
      document.getElementById("tab-body").innerHTML = `
        <div class="toolbar">
          <button class="btn btn-primary" id="btn-new-aws" type="button">${t("admin.aws.create")}</button>
          <button class="btn btn-secondary btn-small" id="btn-refresh" type="button">${t("admin.refresh")}</button>
        </div>
        <p class="sub toolbar-meta">${t("admin.aws.meta", { n: awsCreds.length })} · ${t("admin.aws.defaultHint")}</p>
        <div style="overflow:auto">
          <table class="data">
            <thead><tr>
              <th>${t("admin.aws.default")}</th>
              <th>${t("admin.name")}</th>
              <th>${t("admin.aws.accessKey")}</th>
              <th>${t("admin.limits")}</th>
              <th>${t("admin.aws.tokensMonth")}</th>
              <th>${t("admin.aws.byModel")}</th>
              <th>${t("admin.status")}</th>
              <th></th>
            </tr></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>`;
      const tbody = document.getElementById("tbody");
      if (!awsCreds.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty">${t("admin.aws.empty")}</td></tr>`;
      } else {
        tbody.innerHTML = awsCreds
          .map((c) => {
            const models = c.allowed_models?.length
              ? `<div style="color:var(--muted);font-size:0.72rem" title="${esc(c.allowed_models.join(", "))}">${t("admin.nModelsLimited", { n: c.allowed_models.length })}</div>`
              : `<div style="color:var(--muted);font-size:0.72rem">${t("admin.allModels")}</div>`;
            const byModel = (c.models_usage || []).length
              ? `<div class="aws-model-usage">${(c.models_usage || [])
                  .slice(0, 5)
                  .map(
                    (u) =>
                      `<div title="${esc(u.model)}"><span class="mono">${esc(shortModel(u.model))}</span> <strong>${num(u.total_tokens)}</strong> <span class="sub">(${num(u.request_count)})</span></div>`,
                  )
                  .join("")}</div>`
              : `<span class="sub">—</span>`;
            return `<tr class="${c.is_default ? "aws-default-row" : ""}">
              <td>${
                c.is_default
                  ? `<span class="badge badge-ok">${t("admin.aws.defaultBadge")}</span>`
                  : `<button class="btn btn-secondary btn-small" data-aws-default="${esc(c.cred_id)}" type="button">${t("admin.aws.setDefault")}</button>`
              }</td>
              <td><strong>${esc(c.name)}</strong><div class="sub mono" style="font-size:0.72rem">${esc(c.region || "—")} · p${num(c.priority)}</div></td>
              <td class="mono">${esc(c.access_key_id_masked)}</td>
              <td>${models}</td>
              <td>
                <strong>${num(c.total_tokens_month)}</strong>
                <div class="sub" style="font-size:0.72rem">${t("stat.requests")}: ${num(c.request_count_month)}</div>
                <div class="sub" style="font-size:0.72rem">in ${num(c.prompt_tokens_month)} / out ${num(c.completion_tokens_month)}</div>
              </td>
              <td>${byModel}</td>
              <td>${c.enabled ? `<span class="badge badge-ok">${t("admin.aws.enabled")}</span>` : `<span class="badge badge-off">${t("admin.aws.disabled")}</span>`}</td>
              <td class="actions">
                <button class="btn btn-secondary btn-small" data-aws-edit="${esc(c.cred_id)}" type="button">${t("admin.aws.edit")}</button>
                <button class="btn btn-secondary btn-small" data-aws-toggle="${esc(c.cred_id)}" data-enabled="${c.enabled ? "1" : "0"}" type="button">${c.enabled ? t("admin.aws.disable") : t("admin.aws.enable")}</button>
                <button class="btn btn-danger btn-small" data-aws-del="${esc(c.cred_id)}" type="button">${t("admin.delete")}</button>
              </td>
            </tr>`;
          })
          .join("");
      }
      document.getElementById("btn-new-aws").onclick = () => openAwsModal(null);
      document.getElementById("btn-refresh").onclick = load;
      tbody.querySelectorAll("[data-aws-default]").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await api(`/aws-credentials/${btn.dataset.awsDefault}/default`, {
              method: "POST",
              admin: true,
              token: adminToken(),
            });
            setAlert("ok", t("admin.aws.defaultOk"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
      tbody.querySelectorAll("[data-aws-edit]").forEach((btn) => {
        btn.onclick = () => {
          const row = awsCreds.find((c) => c.cred_id === btn.dataset.awsEdit);
          if (row) openAwsModal(row);
        };
      });
      tbody.querySelectorAll("[data-aws-toggle]").forEach((btn) => {
        btn.onclick = async () => {
          const on = btn.dataset.enabled === "1";
          try {
            await api(`/aws-credentials/${btn.dataset.awsToggle}`, {
              method: "PATCH",
              admin: true,
              token: adminToken(),
              body: { enabled: !on },
            });
            setAlert("ok", on ? t("admin.aws.disabledOk") : t("admin.aws.enabledOk"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
      tbody.querySelectorAll("[data-aws-del]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm(t("admin.aws.confirmDelete"))) return;
          try {
            await api(`/aws-credentials/${btn.dataset.awsDel}`, {
              method: "DELETE",
              admin: true,
              token: adminToken(),
            });
            setAlert("ok", t("admin.aws.deleted"));
            await load();
          } catch (err) {
            setAlert("error", err.message);
          }
        };
      });
    }

    function statusBadge(code) {
      const n = Number(code || 0);
      if (n >= 500) return `<span class="badge badge-off">${n}</span>`;
      if (n >= 400) return `<span class="badge badge-warn">${n}</span>`;
      if (n >= 200 && n < 300) return `<span class="badge badge-ok">${n}</span>`;
      return `<span class="badge badge-muted">${n || "—"}</span>`;
    }

    function methodBadge(method) {
      const m = String(method || "").toUpperCase();
      const cls = m === "POST" ? "badge-off" : m === "GET" ? "badge-ok" : "badge-muted";
      return `<span class="badge ${cls}">${esc(m || "—")}</span>`;
    }

    function renderLogPager() {
      const pager = document.getElementById("log-pager");
      if (!pager) return;
      const totalPages = Math.max(1, Math.ceil(logTotal / LOG_PAGE_SIZE));
      if (logTotal <= LOG_PAGE_SIZE) {
        pager.hidden = true;
        pager.innerHTML = "";
        return;
      }
      pager.hidden = false;
      if (logPage > totalPages) logPage = totalPages;
      const windowSize = 7;
      let start = Math.max(1, logPage - Math.floor(windowSize / 2));
      let end = Math.min(totalPages, start + windowSize - 1);
      start = Math.max(1, end - windowSize + 1);
      const pages = [];
      for (let p = start; p <= end; p += 1) pages.push(p);
      pager.innerHTML = `
        <button type="button" class="pager-btn" data-page="prev" ${logPage <= 1 ? "disabled" : ""}>${t("usage.prev")}</button>
        ${start > 1 ? `<button type="button" class="pager-btn" data-page="1">1</button>${start > 2 ? `<span class="pager-ellipsis">…</span>` : ""}` : ""}
        ${pages
          .map((p) => `<button type="button" class="pager-btn ${p === logPage ? "active" : ""}" data-page="${p}">${p}</button>`)
          .join("")}
        ${end < totalPages ? `${end < totalPages - 1 ? `<span class="pager-ellipsis">…</span>` : ""}<button type="button" class="pager-btn" data-page="${totalPages}">${totalPages}</button>` : ""}
        <button type="button" class="pager-btn" data-page="next" ${logPage >= totalPages ? "disabled" : ""}>${t("usage.next")}</button>
        <span class="pager-meta">${t("usage.pageOf", { page: logPage, pages: totalPages })}</span>`;
      pager.querySelectorAll("[data-page]").forEach((btn) => {
        btn.onclick = () => {
          const v = btn.dataset.page;
          const total = Math.max(1, Math.ceil(logTotal / LOG_PAGE_SIZE));
          let next = logPage;
          if (v === "prev") next = Math.max(1, logPage - 1);
          else if (v === "next") next = Math.min(total, logPage + 1);
          else next = Number(v) || 1;
          if (next === logPage) return;
          logPage = next;
          loadRequestLogs();
        };
      });
    }

    async function banIp(ip, reason) {
      const clean = String(ip || "").trim();
      if (!clean) return;
      if (!confirm(t("admin.logs.banConfirm", { ip: clean }))) return;
      try {
        await api("/banned-ips", {
          admin: true,
          token: adminToken(),
          method: "POST",
          body: { ip: clean, reason: reason || t("admin.logs.banReasonManual") },
        });
        setAlert("ok", t("admin.logs.banOk", { ip: clean }));
        await loadRequestLogs();
      } catch (err) {
        setAlert("error", err.message);
      }
    }

    async function unbanIp(ip) {
      const clean = String(ip || "").trim();
      if (!clean) return;
      if (!confirm(t("admin.logs.unbanConfirm", { ip: clean }))) return;
      try {
        await api(`/banned-ips/${encodeURIComponent(clean)}`, {
          admin: true,
          token: adminToken(),
          method: "DELETE",
        });
        setAlert("ok", t("admin.logs.unbanOk", { ip: clean }));
        await loadRequestLogs();
      } catch (err) {
        setAlert("error", err.message);
      }
    }

    function paintLogs() {
      document.getElementById("tab-body").innerHTML = `
        <p class="sub">${t("admin.logs.hint")}</p>
        <div class="toolbar usage-filter-bar log-filter-bar">
          <input id="log-ip" type="text" value="${esc(logFilters.ip)}" placeholder="${t("admin.logs.filterIp")}" />
          <select id="log-method">
            <option value="">${t("admin.logs.methodAll")}</option>
            ${["GET", "POST", "PATCH", "DELETE"].map((m) => `<option value="${m}" ${logFilters.method === m ? "selected" : ""}>${m}</option>`).join("")}
          </select>
          <select id="log-status">
            <option value="">${t("admin.logs.statusAll")}</option>
            <option value="2xx" ${logFilters.status === "2xx" ? "selected" : ""}>2xx</option>
            <option value="4xx" ${logFilters.status === "4xx" ? "selected" : ""}>4xx</option>
            <option value="5xx" ${logFilters.status === "5xx" ? "selected" : ""}>5xx</option>
            <option value="401" ${logFilters.status === "401" ? "selected" : ""}>401</option>
            <option value="403" ${logFilters.status === "403" ? "selected" : ""}>403</option>
            <option value="429" ${logFilters.status === "429" ? "selected" : ""}>429</option>
          </select>
          <input id="log-path" type="text" value="${esc(logFilters.path)}" placeholder="${t("admin.logs.filterPath")}" />
          <label class="check-inline"><input type="checkbox" id="log-errors" ${logFilters.errorsOnly ? "checked" : ""} /> ${t("admin.logs.errorsOnly")}</label>
          <button class="btn btn-primary btn-small" id="log-apply" type="button">${t("admin.view")}</button>
          <button class="btn btn-secondary btn-small" id="log-refresh" type="button">${t("admin.refresh")}</button>
        </div>
        <div class="usage-admin-grid log-admin-grid">
          <div>
            <div class="toolbar" style="margin-bottom:0.5rem">
              <h3 class="usage-section-title" style="margin:0">${t("admin.logs.requests")}</h3>
              <span class="sub" id="log-count"></span>
            </div>
            <div class="usage-table-wrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>${t("admin.logs.col.time")}</th>
                    <th>${t("admin.logs.col.ip")}</th>
                    <th>${t("admin.logs.col.method")}</th>
                    <th>${t("admin.logs.col.path")}</th>
                    <th>${t("admin.logs.col.status")}</th>
                    <th>${t("admin.logs.col.latency")}</th>
                    <th>${t("admin.logs.col.error")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody id="log-rows"><tr><td colspan="8" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
            <nav class="pager" id="log-pager" hidden></nav>
          </div>
          <div>
            <h3 class="usage-section-title">${t("admin.logs.ipSpam")}</h3>
            <p class="sub">${t("admin.logs.ipSpamHint")}</p>
            <div class="usage-table-wrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>${t("admin.logs.col.ip")}</th>
                    <th>${t("stat.requests")}</th>
                    <th>${t("admin.logs.col.errors")}</th>
                    <th>${t("admin.logs.col.lastSeen")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody id="log-ip-rows"><tr><td colspan="5" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
            <h3 class="usage-section-title" style="margin-top:1.25rem">${t("admin.logs.bannedTitle")}</h3>
            <p class="sub">${t("admin.logs.bannedHint")}</p>
            <div class="usage-table-wrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>${t("admin.logs.col.ip")}</th>
                    <th>${t("admin.logs.col.reason")}</th>
                    <th>${t("admin.logs.col.source")}</th>
                    <th>${t("admin.logs.col.time")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody id="log-banned-rows"><tr><td colspan="5" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
            <div class="toolbar" style="margin-top:1.25rem;align-items:center">
              <h3 class="usage-section-title" style="margin:0">${t("admin.logs.loginTitle")}</h3>
              <button class="btn btn-secondary btn-small" id="btn-gen-2fa" type="button">${t("admin.logs.gen2fa")}</button>
              <span class="sub" id="twofa-status"></span>
            </div>
            <p class="sub">${t("admin.logs.loginHint")}</p>
            <div class="usage-table-wrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>${t("admin.logs.col.time")}</th>
                    <th>${t("admin.logs.col.ip")}</th>
                    <th>${t("admin.logs.col.result")}</th>
                    <th>${t("admin.logs.col.detail")}</th>
                  </tr>
                </thead>
                <tbody id="log-login-rows"><tr><td colspan="4" class="empty">${t("admin.loadingDots")}</td></tr></tbody>
              </table>
            </div>
          </div>
        </div>`;

      document.getElementById("log-apply").onclick = () => {
        logFilters = {
          ip: document.getElementById("log-ip").value.trim(),
          method: document.getElementById("log-method").value,
          status: document.getElementById("log-status").value,
          path: document.getElementById("log-path").value.trim(),
          errorsOnly: document.getElementById("log-errors").checked,
        };
        loadRequestLogs({ resetPage: true });
      };
      document.getElementById("log-refresh").onclick = () => loadRequestLogs();
      document.getElementById("btn-gen-2fa").onclick = async () => {
        if (!confirm(t("admin.logs.gen2faConfirm"))) return;
        try {
          const data = await api("/2fa/generate", {
            method: "POST",
            admin: true,
            token: adminToken(),
          });
          showModal(`
            <h3>${t("admin.logs.gen2faTitle")}</h3>
            <p class="sub">${t("admin.logs.gen2faOnceTotp")}</p>
            <div class="field"><label>${t("admin.logs.totpSecret")}</label>
              <textarea id="m-new-2fa" class="mono cdk-new-ta" readonly rows="3">${esc(data.secret || "")}</textarea>
            </div>
            <div class="field"><label>${t("admin.logs.totpUri")}</label>
              <textarea id="m-otpauth" class="mono cdk-new-ta" readonly rows="3">${esc(data.otpauth_url || "")}</textarea>
            </div>
            <p class="sub">${t("admin.logs.totpNow", { code: data.otp || "------" })}</p>
            <div class="actions">
              <button class="btn btn-primary" id="m-copy-2fa" type="button">${t("admin.logs.copySecret")}</button>
              <button class="btn btn-secondary" id="m-close-2fa" type="button">${t("admin.close")}</button>
            </div>`);
          document.getElementById("m-close-2fa").onclick = closeModal;
          document.getElementById("m-copy-2fa").onclick = async () => {
            await copyText(data.secret || "");
            setAlert("ok", t("admin.logs.gen2faCopied"));
          };
          const inp = document.getElementById("m-new-2fa");
          if (inp) {
            inp.focus();
            inp.select();
          }
          loadRequestLogs();
        } catch (err) {
          setAlert("error", err.message);
        }
      };
    }

    async function loadRequestLogs({ resetPage = false } = {}) {
      if (resetPage) logPage = 1;
      const params = new URLSearchParams({
        limit: String(LOG_PAGE_SIZE),
        offset: String((logPage - 1) * LOG_PAGE_SIZE),
      });
      if (logFilters.ip) params.set("ip", logFilters.ip);
      if (logFilters.method) params.set("method", logFilters.method);
      if (logFilters.status) params.set("status", logFilters.status);
      if (logFilters.path) params.set("path", logFilters.path);
      if (logFilters.errorsOnly) params.set("errors_only", "true");

      const rowsEl = document.getElementById("log-rows");
      const ipRowsEl = document.getElementById("log-ip-rows");
      const bannedRowsEl = document.getElementById("log-banned-rows");
      const loginRowsEl = document.getElementById("log-login-rows");
      const twofaStatusEl = document.getElementById("twofa-status");
      const countEl = document.getElementById("log-count");
      if (rowsEl) rowsEl.innerHTML = `<tr><td colspan="8" class="empty">${t("admin.loadingDots")}</td></tr>`;

      try {
        const [history, ipSummary, bannedList, loginLogs, twofa] = await Promise.all([
          api(`/request-logs?${params}`, { admin: true, token: adminToken() }),
          api("/request-logs/ip-summary?hours=24&limit=30", { admin: true, token: adminToken() }).catch(() => []),
          api("/banned-ips", { admin: true, token: adminToken() }).catch(() => []),
          api("/login-logs?limit=50", { admin: true, token: adminToken() }).catch(() => ({ logs: [] })),
          api("/2fa", { admin: true, token: adminToken() }).catch(() => ({ enabled: false })),
        ]);
        logTotal = Number(history.total || 0);
        logIpSummary = Array.isArray(ipSummary) ? ipSummary : [];
        const banned = Array.isArray(bannedList) ? bannedList : [];
        const bannedSet = new Set(banned.map((b) => b.ip));
        const logs = history.logs || [];
        const offset = (logPage - 1) * LOG_PAGE_SIZE;
        const from = logTotal ? offset + 1 : 0;
        const to = offset + logs.length;
        if (countEl) {
          countEl.textContent = logTotal
            ? t("usage.pageRange", { from, to, total: logTotal })
            : t("admin.logs.empty");
        }
        if (rowsEl) {
          rowsEl.innerHTML = logs.length
            ? logs
                .map((row) => {
                  const time = row.created_at
                    ? new Date(row.created_at).toLocaleString(I18N.localeTag(), {
                        month: "2-digit",
                        day: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })
                    : "—";
                  const ip = row.client_ip || "";
                  const banBtn = ip
                    ? bannedSet.has(ip)
                      ? `<span class="badge badge-off">${t("admin.logs.banned")}</span>`
                      : `<button class="btn btn-danger btn-small log-ban-ip" type="button" data-ip="${esc(ip)}">${t("admin.logs.ban")}</button>`
                    : "—";
                  return `<tr>
                    <td>${esc(time)}</td>
                    <td class="mono" title="${esc(ip)}">${esc(ip || "—")}</td>
                    <td>${methodBadge(row.method)}</td>
                    <td class="mono log-path" title="${esc(row.path || "")}">${esc(row.path || "—")}</td>
                    <td>${statusBadge(row.status_code)}</td>
                    <td>${num(row.latency_ms)} ms</td>
                    <td class="log-error" title="${esc(row.error || "")}">${esc(row.error || "—")}</td>
                    <td>${banBtn}</td>
                  </tr>`;
                })
                .join("")
            : `<tr><td colspan="8" class="empty">${t("admin.logs.empty")}</td></tr>`;
          rowsEl.querySelectorAll(".log-ban-ip").forEach((btn) => {
            btn.onclick = () => banIp(btn.dataset.ip, t("admin.logs.banReasonManual"));
          });
        }
        if (ipRowsEl) {
          ipRowsEl.innerHTML = logIpSummary.length
            ? logIpSummary
                .map((row) => {
                  const ip = row.client_ip || "";
                  const banBtn = ip
                    ? bannedSet.has(ip)
                      ? `<span class="badge badge-off">${t("admin.logs.banned")}</span>`
                      : `<button class="btn btn-danger btn-small log-ban-ip" type="button" data-ip="${esc(ip)}">${t("admin.logs.ban")}</button>`
                    : "";
                  return `<tr class="${row.error_count > 0 ? "log-ip-hot" : ""}">
                    <td class="mono"><button type="button" class="linkish log-ip-filter" data-ip="${esc(ip)}">${esc(ip)}</button></td>
                    <td>${num(row.request_count)}</td>
                    <td>${row.error_count ? `<span class="badge badge-off">${num(row.error_count)}</span>` : "0"}</td>
                    <td>${esc(row.last_seen ? new Date(row.last_seen).toLocaleString(I18N.localeTag()) : "—")}</td>
                    <td>${banBtn}</td>
                  </tr>`;
                })
                .join("")
            : `<tr><td colspan="5" class="empty">${t("admin.logs.ipEmpty")}</td></tr>`;
          ipRowsEl.querySelectorAll(".log-ip-filter").forEach((btn) => {
            btn.onclick = () => {
              logFilters.ip = btn.dataset.ip || "";
              const ipInput = document.getElementById("log-ip");
              if (ipInput) ipInput.value = logFilters.ip;
              loadRequestLogs({ resetPage: true });
            };
          });
          ipRowsEl.querySelectorAll(".log-ban-ip").forEach((btn) => {
            btn.onclick = () => banIp(btn.dataset.ip, t("admin.logs.banReasonSpam"));
          });
        }
        if (bannedRowsEl) {
          bannedRowsEl.innerHTML = banned.length
            ? banned
                .map((row) => {
                  const time = row.created_at
                    ? new Date(row.created_at).toLocaleString(I18N.localeTag())
                    : "—";
                  return `<tr>
                    <td class="mono">${esc(row.ip)}</td>
                    <td>${esc(row.reason || "—")}</td>
                    <td><span class="badge badge-muted">${esc(row.source || "—")}</span></td>
                    <td>${esc(time)}</td>
                    <td><button class="btn btn-secondary btn-small log-unban-ip" type="button" data-ip="${esc(row.ip)}">${t("admin.logs.unban")}</button></td>
                  </tr>`;
                })
                .join("")
            : `<tr><td colspan="5" class="empty">${t("admin.logs.bannedEmpty")}</td></tr>`;
          bannedRowsEl.querySelectorAll(".log-unban-ip").forEach((btn) => {
            btn.onclick = () => unbanIp(btn.dataset.ip);
          });
        }
        if (twofaStatusEl) {
          twofaStatusEl.textContent = twofa?.enabled
            ? t("admin.logs.twofaOn")
            : t("admin.logs.twofaOff");
        }
        if (loginRowsEl) {
          const loginRows = loginLogs?.logs || [];
          loginRowsEl.innerHTML = loginRows.length
            ? loginRows
                .map((row) => {
                  const time = row.created_at
                    ? new Date(row.created_at).toLocaleString(I18N.localeTag())
                    : "—";
                  const ok = !!row.success;
                  return `<tr>
                    <td>${esc(time)}</td>
                    <td class="mono">${esc(row.client_ip || "—")}</td>
                    <td>${ok ? `<span class="badge badge-ok">${t("admin.logs.loginOk")}</span>` : `<span class="badge badge-off">${t("admin.logs.loginFail")}</span>`}</td>
                    <td class="mono">${esc(row.detail || "—")}</td>
                  </tr>`;
                })
                .join("")
            : `<tr><td colspan="4" class="empty">${t("admin.logs.loginEmpty")}</td></tr>`;
        }
        renderLogPager();
      } catch (err) {
        if (rowsEl) rowsEl.innerHTML = `<tr><td colspan="8" class="empty">${esc(err.message)}</td></tr>`;
        setAlert("error", err.message);
      }
    }

    function paint() {
      paintStats();
      if (tab === "cdks") paintCdks();
      else if (tab === "keys") paintKeys();
      else if (tab === "aws") paintAws();
      else if (tab === "logs") paintLogs();
      else paintUsage();
    }

    async function load() {
      try {
        const include = document.getElementById("inc-revoked")?.checked || false;
        const statsEl = document.getElementById("stats");
        if (statsEl) {
          statsEl.innerHTML = `
            <div class="stat"><div class="n">…</div><div class="l">${t("admin.loading")}</div></div>
            <div class="stat"><div class="n">…</div><div class="l">${t("admin.loadingKeys")}</div></div>`;
        }
        const [cdkData, keyData, awsData] = await Promise.all([
          api("/cdks?include_redeemed=true", { admin: true, token: adminToken() }),
          api(`/keys?include_revoked=${include}`, { admin: true, token: adminToken() }),
          api("/aws-credentials", { admin: true, token: adminToken() }).catch(() => []),
        ]);
        cdks = cdkData;
        keys = keyData;
        awsCreds = Array.isArray(awsData) ? awsData : [];
        paint();
        // Prefetch models in background (does not block dashboard paint).
        ensureModels();
        if (tab === "usage") await loadUsageReport();
        if (tab === "logs") await loadRequestLogs({ resetPage: true });
      } catch (err) {
        const status = Number(err && err.status) || 0;
        const msg = String(err && err.message ? err.message : err).toLowerCase();
        if (status === 401 || msg.includes("invalid admin") || msg.includes("unauthorized") || msg.includes("sign in")) {
          localStorage.removeItem(S.adminToken);
          location.hash = `${ADMIN_UI}/login`;
          route();
          return;
        }
        setAlert("error", err.message);
      }
    }

    await load();
  }

  function renderUserRedeem() {
    const existing = userKey();
    app.innerHTML = `
      <section class="panel auth-shell">
        <h1>${t("user.title")}</h1>
        <p class="sub">${t("user.sub")}</p>
        <div id="alert"></div>
        <div class="field"><label>${t("user.cdk")}</label><input id="cdk" placeholder="CDK-XXXX-XXXX-XXXX" autocomplete="off" /></div>
        <button class="btn btn-primary btn-block" id="btn-redeem" type="button">${t("user.redeem")}</button>
        <div id="result" class="redeem-result"></div>
        ${existing ? `<p class="sub" style="margin-top:1rem">${t("user.hasKey")} <a href="#/chat">${t("user.goChat")}</a> · <a href="#/usage">${t("user.goUsage")}</a></p>` : ""}
      </section>`;
    const alert = document.getElementById("alert");
    const result = document.getElementById("result");
    const btn = document.getElementById("btn-redeem");
    const showKey = (apiKey, meta = {}) => {
      result.innerHTML = `
        <div class="redeem-success">
          <p class="redeem-label">${t("user.keyLabel")}</p>
          <div class="key-reveal mono" id="user-key-out" tabindex="0">${esc(apiKey)}</div>
          <div class="actions">
            <button class="btn btn-primary" id="btn-copy" type="button">${t("user.copyKey")}</button>
            <a class="btn btn-secondary" href="#/chat">${t("user.goChat")}</a>
            <a class="btn btn-secondary" href="#/usage">${t("user.goUsage")}</a>
          </div>
          <p class="sub">${t("user.quotaLine", {
            rpm: num(meta.rpm_limit),
            quota: meta.monthly_token_quota > 0 ? num(meta.monthly_token_quota) : "∞",
          })}</p>
          <p class="sub">${t("user.saveHint")}</p>
        </div>`;
      const out = document.getElementById("user-key-out");
      if (out) {
        const range = document.createRange();
        range.selectNodeContents(out);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      document.getElementById("btn-copy").onclick = async () => {
        const ok = await copyText(apiKey);
        alert.innerHTML = alertHtml(ok ? "ok" : "warn", ok ? t("admin.copiedKey") : t("user.copyFail"));
      };
    };
    btn.onclick = async () => {
      const cdk = document.getElementById("cdk").value.trim();
      if (!cdk) {
        alert.innerHTML = alertHtml("warn", t("user.needCdk"));
        return;
      }
      setBusy(btn, true, t("user.working"), t("user.redeem"));
      alert.innerHTML = alertHtml("warn", t("user.working"));
      result.innerHTML = `<div class="empty">${t("user.working")}</div>`;
      try {
        const data = await api("/redeem", {
          method: "POST",
          body: { cdk },
          timeoutMs: 30000,
        });
        if (!data?.api_key) throw new Error(t("user.noKey"));
        localStorage.setItem(S.userKey, data.api_key);
        alert.innerHTML = alertHtml("ok", t("user.ok"));
        showKey(data.api_key, data);
        await copyText(data.api_key);
      } catch (err) {
        alert.innerHTML = alertHtml("error", err.message);
        result.innerHTML = "";
      } finally {
        setBusy(btn, false, null, t("user.redeem"));
      }
    };
    document.getElementById("cdk").addEventListener("keydown", (e) => {
      if (e.key === "Enter") btn.click();
    });
  }

  async function renderUsage() {
    const saved = userKey();
    app.innerHTML = `
      <section class="usage-page">
        <div class="usage-toolbar">
          <div>
            <h1>${t("usage.title")}</h1>
            <p class="sub">${t("usage.sub")}</p>
          </div>
          <div class="usage-toolbar-actions">
            <div class="field usage-key-field">
              <label>${t("usage.apiKey")}</label>
              ${passwordFieldInner("usage-key", saved, "bag_...")}
            </div>
            <button class="btn btn-primary" id="usage-load" type="button">${t("usage.check")}</button>
            <button class="btn btn-secondary" id="usage-refresh" type="button">${t("admin.refresh")}</button>
          </div>
        </div>
        <div id="usage-alert"></div>
        <div class="stats usage-stats" id="usage-stats">
          <div class="stat"><div class="n">—</div><div class="l">${t("usage.used")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("usage.remaining")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.input")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.output")}</div></div>
          <div class="stat"><div class="n">—</div><div class="l">${t("stat.requests")}</div></div>
        </div>
        <div id="usage-meter"></div>
        <div class="usage-list-head">
          <span>${t("usage.history")}</span>
          <span id="usage-count" class="sub"></span>
        </div>
        <div class="usage-list" id="usage-rows">
          <div class="empty">${t("usage.emptyHint")}</div>
        </div>
        <nav class="pager" id="usage-pager" hidden></nav>
      </section>`;

    bindPasswordToggles(app);
    const alert = document.getElementById("usage-alert");
    const PAGE_SIZE = 20;
    let usagePage = 1;
    let usageTotal = 0;
    const setAlert = (type, message) => {
      alert.innerHTML = alertHtml(type, message);
    };
    const formatTime = (value) => {
      if (!value) return "—";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString(I18N.localeTag(), {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        day: "2-digit",
        month: "2-digit",
      });
    };
    const shortModel = (model) => {
      const value = String(model || "—");
      return value
        .replace(/^us\.anthropic\./, "")
        .replace(/^global\.anthropic\./, "")
        .replace(/^anthropic\./, "");
    };
    const shortIp = (ip) => {
      const value = String(ip || "").trim();
      if (!value) return "—";
      if (value.includes(":")) {
        const parts = value.split(":");
        return `${parts.slice(0, 2).join(":")}…${parts.slice(-1)[0]}`;
      }
      return value;
    };
    const fmtLatency = (ms) => {
      const n = Number(ms || 0);
      if (!n) return "—";
      return `${Math.round(n).toLocaleString(I18N.localeTag())} ms`;
    };

    function renderPager() {
      const pager = document.getElementById("usage-pager");
      if (!pager) return;
      const totalPages = Math.max(1, Math.ceil(usageTotal / PAGE_SIZE));
      if (usageTotal <= PAGE_SIZE) {
        pager.hidden = true;
        pager.innerHTML = "";
        return;
      }
      pager.hidden = false;
      if (usagePage > totalPages) usagePage = totalPages;
      const windowSize = 7;
      let start = Math.max(1, usagePage - Math.floor(windowSize / 2));
      let end = Math.min(totalPages, start + windowSize - 1);
      start = Math.max(1, end - windowSize + 1);
      const pages = [];
      for (let p = start; p <= end; p += 1) pages.push(p);
      pager.innerHTML = `
        <button type="button" class="pager-btn" data-page="prev" ${usagePage <= 1 ? "disabled" : ""}>${t("usage.prev")}</button>
        ${start > 1 ? `<button type="button" class="pager-btn" data-page="1">1</button>${start > 2 ? `<span class="pager-ellipsis">…</span>` : ""}` : ""}
        ${pages
          .map(
            (p) =>
              `<button type="button" class="pager-btn ${p === usagePage ? "active" : ""}" data-page="${p}">${p}</button>`,
          )
          .join("")}
        ${end < totalPages ? `${end < totalPages - 1 ? `<span class="pager-ellipsis">…</span>` : ""}<button type="button" class="pager-btn" data-page="${totalPages}">${totalPages}</button>` : ""}
        <button type="button" class="pager-btn" data-page="next" ${usagePage >= totalPages ? "disabled" : ""}>${t("usage.next")}</button>
        <span class="pager-meta">${t("usage.pageOf", { page: usagePage, pages: totalPages })}</span>`;
      pager.querySelectorAll("[data-page]").forEach((btn) => {
        btn.onclick = () => {
          const v = btn.dataset.page;
          const total = Math.max(1, Math.ceil(usageTotal / PAGE_SIZE));
          let next = usagePage;
          if (v === "prev") next = Math.max(1, usagePage - 1);
          else if (v === "next") next = Math.min(total, usagePage + 1);
          else next = Number(v) || 1;
          if (next === usagePage) return;
          usagePage = next;
          loadUsage({ stats: false });
        };
      });
    }

    function paintLogRows(logs) {
      document.getElementById("usage-rows").innerHTML = logs.length
        ? logs
            .map(
              (row) => `<article class="usage-row">
                <div class="usage-row-main">
                  <div class="usage-row-top">
                    <time>${esc(formatTime(row.created_at))}</time>
                    <span class="usage-model" title="${esc(row.model)}">${esc(shortModel(row.model))}</span>
                  </div>
                  <div class="usage-meta">
                    <span title="${esc(row.client_ip || "")}">${esc(shortIp(row.client_ip))}</span>
                    <span>${esc(fmtLatency(row.latency_ms))}</span>
                  </div>
                </div>
                <div class="usage-tokens">
                  <div class="tok"><span>${t("stat.input")}</span><strong>${num(row.prompt_tokens)}</strong></div>
                  <div class="tok"><span>${t("stat.output")}</span><strong>${num(row.completion_tokens)}</strong></div>
                  <div class="tok"><span>${t("stat.cacheRW")}</span><strong>${num(row.cache_read_tokens)} / ${num(row.cache_write_tokens)}</strong></div>
                  <div class="tok tok-total"><span>${t("stat.totalTokens")}</span><strong>${num(row.total_tokens)}</strong></div>
                </div>
              </article>`,
            )
            .join("")
        : `<div class="empty">${t("usage.noLogs")}</div>`;
    }

    async function loadUsage({ stats = true, resetPage = false } = {}) {
      const key = document.getElementById("usage-key").value.trim();
      if (!key) return setAlert("warn", t("usage.enterKey"));
      localStorage.setItem(S.userKey, key);
      if (resetPage) usagePage = 1;
      const loadBtn = document.getElementById("usage-load");
      const refreshBtn = document.getElementById("usage-refresh");
      loadBtn.disabled = true;
      refreshBtn.disabled = true;
      try {
        const offset = (usagePage - 1) * PAGE_SIZE;
        const historyPromise = api(`/usage/logs?limit=${PAGE_SIZE}&offset=${offset}`, { token: key });
        let me = null;
        let history;
        if (stats) {
          [me, history] = await Promise.all([api("/me", { token: key }), historyPromise]);
          const quota = Number(me.monthly_token_quota || 0);
          const used = Number(me.total_tokens_month || 0);
          const remaining = quota > 0 ? Math.max(0, quota - used) : null;
          const pct = quota > 0 ? Math.min(100, (used / quota) * 100) : 0;
          document.getElementById("usage-stats").innerHTML = `
            <div class="stat"><div class="n">${num(used)}</div><div class="l">${t("usage.used")}</div></div>
            <div class="stat"><div class="n">${remaining == null ? "∞" : num(remaining)}</div><div class="l">${t("usage.remaining")}</div></div>
            <div class="stat"><div class="n">${num(me.prompt_tokens_month)}</div><div class="l">${t("stat.input")}</div></div>
            <div class="stat"><div class="n">${num(me.completion_tokens_month)}</div><div class="l">${t("stat.output")}</div></div>
            <div class="stat"><div class="n">${num(me.request_count_month)}</div><div class="l">${t("stat.requests")}</div></div>`;
          document.getElementById("usage-meter").innerHTML = `
            <div class="usage-quota-line">
              <span>${t("usage.quotaMonth", { month: esc(me.usage_month || "") })}</span>
              <strong>${quota > 0 ? `${pct.toFixed(1)}% · ${num(used)} / ${num(quota)}` : `${num(used)} / ∞`}</strong>
            </div>
            <div class="meter"><span style="width:${pct}%"></span></div>`;
        } else {
          history = await historyPromise;
        }

        usageTotal = Number(history.total || 0);
        const logs = history.logs || [];
        const from = usageTotal ? offset + 1 : 0;
        const to = offset + logs.length;
        document.getElementById("usage-count").textContent = usageTotal
          ? t("usage.pageRange", { from, to, total: usageTotal })
          : "";
        paintLogRows(logs);
        renderPager();
        setAlert(
          "ok",
          t("usage.loaded", {
            total: usageTotal,
            name: esc(me?.name || ""),
          }),
        );
      } catch (err) {
        setAlert("error", err.message);
      } finally {
        loadBtn.disabled = false;
        refreshBtn.disabled = false;
      }
    }

    document.getElementById("usage-load").onclick = () => loadUsage({ stats: true, resetPage: true });
    document.getElementById("usage-refresh").onclick = () => loadUsage({ stats: true });
    if (saved) loadUsage({ stats: true, resetPage: true });
  }

  async function renderChat() {
    const saved = userKey();
    app.innerHTML = `
      <div class="grid-2">
        <section class="panel">
          <h2>${t("chat.title")}</h2>
          <p class="sub">${t("chat.sub")}</p>
          <div id="alert"></div>
          <div class="row">
            <div class="field" style="flex:2"><label>${t("usage.apiKey")}</label>${passwordFieldInner("key", saved, "bag_...")}</div>
            <div class="field"><label>&nbsp;</label><button class="btn btn-secondary" id="btn-load" type="button">${t("chat.loadModels")}</button></div>
          </div>
          <div class="row">
            <div class="field"><label>${t("chat.model")}</label><select id="model"></select></div>
            <div class="field" style="max-width:140px"><label>${t("chat.maxTokens")}</label><input id="max" type="number" value="1024" min="1" /></div>
          </div>
          <div class="messages" id="messages"><div class="empty">${t("chat.empty")}</div></div>
          <div class="composer">
            <div class="field" style="margin:0"><label>${t("chat.message")}</label><textarea id="prompt"></textarea></div>
            <button class="btn btn-primary" id="btn-send" type="button">${t("chat.send")}</button>
          </div>
        </section>
        <aside class="panel" id="usage"><h2>${t("chat.usageTitle")}</h2><p class="sub">${t("chat.usageHint")}</p></aside>
      </div>`;

    bindPasswordToggles(app);
    const alert = document.getElementById("alert");
    const messages = document.getElementById("messages");
    let history = [];

    const setAlert = (type, m) => {
      alert.innerHTML = alertHtml(type, m);
    };
    const paintMsg = () => {
      if (!history.length) {
        messages.innerHTML = `<div class="empty">${t("chat.empty")}</div>`;
        return;
      }
      messages.innerHTML = history
        .map((m) => `<div class="bubble ${m.role}"><span class="role">${m.role}</span>${esc(m.content)}</div>`)
        .join("");
      messages.scrollTop = messages.scrollHeight;
    };

    async function refresh() {
      const key = document.getElementById("key").value.trim();
      if (!key) return setAlert("warn", t("usage.enterKey"));
      localStorage.setItem(S.userKey, key);
      try {
        const me = await api("/me", { token: key });
        const quota = me.monthly_token_quota || 0;
        const used = me.total_tokens_month || 0;
        const pct = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0;
        document.getElementById("usage").innerHTML = me.is_legacy
          ? `<h2>${t("chat.legacy")}</h2><p class="sub">${t("chat.noQuota")}</p>`
          : `<h2>${esc(me.name)}</h2>
             <p class="sub">${esc(me.key_id)}</p>
             <div class="meter"><span style="width:${pct}%"></span></div>
             <div class="stats" style="grid-template-columns:1fr 1fr;margin:0">
               <div class="stat"><div class="n">${num(used)}</div><div class="l">${t("chat.used")}</div></div>
               <div class="stat"><div class="n">${quota > 0 ? num(quota) : "∞"}</div><div class="l">${t("chat.quota")}</div></div>
               <div class="stat"><div class="n">${num(me.rpm_limit)}</div><div class="l">${t("admin.rpm")}</div></div>
               <div class="stat"><div class="n">${num(me.request_count_month)}</div><div class="l">${t("stat.requests")}</div></div>
             </div>`;
        const models = await api("/models", { token: key });
        const ids = (models.data || []).map((m) => m.id);
        const prefer = [
          "claude-opus-4-6",
          "claude-opus-4-8",
          "claude-fable-5",
        ];
        const ordered = [...prefer.filter((i) => ids.includes(i)), ...ids.filter((i) => !prefer.includes(i))];
        document.getElementById("model").innerHTML = ordered
          .map((id) => `<option value="${esc(id)}">${esc(id)}</option>`)
          .join("");
        setAlert("ok", t("chat.modelsReady", { n: ids.length }));
      } catch (err) {
        setAlert("error", err.message);
      }
    }

    document.getElementById("btn-load").onclick = refresh;
    document.getElementById("btn-send").onclick = async () => {
      const key = document.getElementById("key").value.trim();
      const model = document.getElementById("model").value;
      const prompt = document.getElementById("prompt").value.trim();
      if (!key || !model || !prompt) return setAlert("warn", t("chat.missing"));
      history.push({ role: "user", content: prompt });
      document.getElementById("prompt").value = "";
      paintMsg();
      const btn = document.getElementById("btn-send");
      btn.disabled = true;
      try {
        const data = await api("/chat/completions", {
          method: "POST",
          token: key,
          body: {
            model,
            max_tokens: Number(document.getElementById("max").value || 1024),
            messages: history,
          },
        });
        history.push({ role: "assistant", content: data?.choices?.[0]?.message?.content || "(empty)" });
        paintMsg();
        await refresh();
      } catch (err) {
        history.pop();
        paintMsg();
        setAlert("error", err.message);
      } finally {
        btn.disabled = false;
      }
    };
    if (saved) refresh();
  }

  window.addEventListener("hashchange", route);
  route();
})();
