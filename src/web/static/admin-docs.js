(() => {
  function codeBlock(esc, text, id) {
    return `<div class="code-block"><button class="btn btn-secondary btn-small code-copy" type="button" data-copy-id="${id}">Copy</button><pre id="${id}">${esc(text)}</pre></div>`;
  }

  function endpointBar(esc, method, path, base) {
    const cls = method.toLowerCase();
    const full = `${base}${path}`;
    return `<div class="endpoint-bar">
      <span class="verb ${cls}">${method}</span>
      <span class="path">${esc(path)}</span>
      <button class="btn btn-secondary btn-small copy-btn" type="button" data-copy-text="${esc(full)}">Copy URL</button>
    </div>`;
  }

  function card(title, body) {
    return `<div class="docs-card"><h3>${title}</h3>${body}</div>`;
  }

  window.MrdevAdminDocs = {
    render(app, opts) {
      const { esc, t, adminUi } = opts;
      const I18N = window.MrdevI18n;
      const tr = t || ((k) => (I18N ? I18N.t(k) : k));
      document.body.classList.add("docs-mode");
      document.body.classList.remove("usage-mode");

      const base = `${location.origin}/admin`;
      const hashBase = adminUi || "#/admin";
      const section = (location.hash.split("/")[3] || "intro").toLowerCase();

      app.innerHTML = `
        <div class="docs-shell">
          <aside class="docs-side">
            <div class="side-brand">
              <strong>${esc(tr("adminDocs.brand"))}</strong>
              <small>${esc(tr("adminDocs.brandSub"))}</small>
            </div>
            <div class="docs-base">${esc(base)}</div>
            <div class="docs-group">
              <h4>${esc(tr("adminDocs.group.start"))}</h4>
              <a href="${hashBase}/api-docs/intro" data-sec="intro">${esc(tr("adminDocs.nav.intro"))}</a>
              <a href="${hashBase}/api-docs/auth" data-sec="auth">${esc(tr("adminDocs.nav.auth"))}</a>
            </div>
            <div class="docs-group">
              <h4>${esc(tr("adminDocs.group.keys"))}</h4>
              <a href="${hashBase}/api-docs/keys" data-sec="keys"><span class="method get">CRUD</span> Keys</a>
              <a href="${hashBase}/api-docs/cdks" data-sec="cdks"><span class="method post">CDK</span> CDKs</a>
              <a href="${hashBase}/api-docs/models" data-sec="models"><span class="method get">GET</span> Models</a>
            </div>
            <div class="docs-group">
              <h4>${esc(tr("adminDocs.group.ops"))}</h4>
              <a href="${hashBase}/api-docs/aws" data-sec="aws">AWS credentials</a>
              <a href="${hashBase}/api-docs/usage" data-sec="usage">Usage</a>
              <a href="${hashBase}/api-docs/logs" data-sec="logs">Request logs</a>
              <a href="${hashBase}/api-docs/security" data-sec="security">Ban / 2FA</a>
            </div>
            <div class="docs-group">
              <h4>${esc(tr("adminDocs.group.nav"))}</h4>
              <a href="${hashBase}">${esc(tr("adminDocs.back"))}</a>
              <a href="#/docs">${esc(tr("nav.docs"))}</a>
            </div>
          </aside>
          <div class="docs-main" id="admin-docs-main"></div>
        </div>`;

      const main = document.getElementById("admin-docs-main");
      const pages = {
        intro: () => `
          <div class="docs-hero">
            <div>
              <h1>${esc(tr("adminDocs.title"))}</h1>
              <p class="lead">${esc(tr("adminDocs.lead"))}</p>
            </div>
            <div class="docs-badges">
              <span class="ok">Bearer session</span>
              <span class="ok">ADMIN_API_KEY</span>
              <span>Base: /admin</span>
            </div>
          </div>
          ${card(
            esc(tr("adminDocs.intro.base")),
            `<p>${esc(tr("adminDocs.intro.baseBody"))}</p>
             ${codeBlock(esc, base, "ad-base")}`
          )}
          ${card(
            esc(tr("adminDocs.intro.note")),
            `<ol>
              <li>${esc(tr("adminDocs.intro.n1"))}</li>
              <li>${esc(tr("adminDocs.intro.n2"))}</li>
              <li>${esc(tr("adminDocs.intro.n3"))}</li>
            </ol>`
          )}`,

        auth: () => `
          <h1>${esc(tr("adminDocs.nav.auth"))}</h1>
          <p class="lead">${esc(tr("adminDocs.auth.lead"))}</p>
          ${endpointBar(esc, "POST", "/login", base)}
          ${card(
            "Login",
            `<p>Public (no Bearer). Returns session token.</p>
             ${codeBlock(
               esc,
               `curl -X POST ${base}/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"***","otp":"123456"}'`,
               "ad-login"
             )}
             ${codeBlock(
               esc,
               `{
  "access_token": "<session>",
  "token_type": "bearer",
  "expires_at": "2026-07-18T12:00:00+00:00",
  "username": "admin"
}`,
               "ad-login-resp"
             )}`
          )}
          ${endpointBar(esc, "POST", "/logout", base)}
          ${card(
            "Logout",
            `${codeBlock(
              esc,
              `curl -X POST ${base}/logout \\
  -H "Authorization: Bearer <session-or-ADMIN_API_KEY>"`,
              "ad-logout"
            )}`
          )}
          ${card(
            esc(tr("adminDocs.auth.header")),
            `${codeBlock(esc, `Authorization: Bearer <access_token_or_ADMIN_API_KEY>`, "ad-hdr")}`
          )}`,

        keys: () => `
          <h1>API Keys</h1>
          <p class="lead">Create / list / update / revoke user <code>bag_</code> keys.</p>
          ${endpointBar(esc, "POST", "/keys", base)}
          ${card(
            "Create key",
            `${codeBlock(
              esc,
              `curl -X POST ${base}/keys \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "customer-a",
    "rpm_limit": 60,
    "monthly_token_quota": 2000000,
    "allowed_models": ["claude-opus-4-6"]
  }'`,
              "ad-key-create"
            )}
            <p>Response includes <code>api_key</code> once. Tier tips: <code>claude-opus-4-6</code> / <code>claude-opus-4-8</code> / <code>claude-fable-5</code> (ceiling) or omit for unlimited.</p>`
          )}
          ${endpointBar(esc, "GET", "/keys?include_revoked=false", base)}
          ${endpointBar(esc, "GET", "/keys/{key_id}", base)}
          ${endpointBar(esc, "PATCH", "/keys/{key_id}", base)}
          ${endpointBar(esc, "DELETE", "/keys/{key_id}", base)}
          <p class="lead">Soft revoke. Hard delete: <code>DELETE /keys/{key_id}/hard</code></p>`,

        cdks: () => `
          <h1>CDK</h1>
          <p class="lead">Issue redeem codes users exchange at <code>POST /api/v1/redeem</code>.</p>
          ${endpointBar(esc, "POST", "/cdks", base)}
          ${card(
            "Create CDKs",
            `${codeBlock(
              esc,
              `curl -X POST ${base}/cdks \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "label": "user",
    "count": 5,
    "rpm_limit": 60,
    "monthly_token_quota": 2000000,
    "allowed_models": ["claude-opus-4-6"]
  }'`,
              "ad-cdk-create"
            )}`
          )}
          ${endpointBar(esc, "GET", "/cdks?include_redeemed=true", base)}
          ${endpointBar(esc, "DELETE", "/cdks/{code}", base)}
          <p>Soft revoke. Hard delete: <code>DELETE /cdks/{code}/hard</code></p>`,

        models: () => `
          <h1>Models</h1>
          ${endpointBar(esc, "GET", "/models", base)}
          ${card(
            "List public model IDs",
            `<p>Short names for admin pickers (e.g. <code>claude-opus-4-6</code>).</p>
             ${codeBlock(
               esc,
               `curl ${base}/models -H "Authorization: Bearer $TOKEN"`,
               "ad-models"
             )}`
          )}`,

        aws: () => `
          <h1>Upstream credentials</h1>
          <p class="lead">Pool of upstream keys used by the gateway (admin only).</p>
          ${endpointBar(esc, "GET", "/aws-credentials", base)}
          ${endpointBar(esc, "POST", "/aws-credentials", base)}
          ${endpointBar(esc, "PATCH", "/aws-credentials/{cred_id}", base)}
          ${endpointBar(esc, "DELETE", "/aws-credentials/{cred_id}", base)}
          ${endpointBar(esc, "POST", "/aws-credentials/{cred_id}/default", base)}
          ${card(
            "Create (shape)",
            `${codeBlock(
              esc,
              `{
  "name": "pool-1",
  "access_key_id": "AKIA...",
  "secret_access_key": "...",
  "session_token": "",
  "region": "us-west-2",
  "allowed_models": [],
  "priority": 100,
  "enabled": true,
  "is_default": false
}`,
              "ad-aws-body"
            )}
            <p>Empty <code>allowed_models</code> = wildcard. Explicit list = only those models on that key.</p>`
          )}`,

        usage: () => `
          <h1>Usage</h1>
          ${endpointBar(esc, "GET", "/usage/summary?period=day&day=2026-07-18", base)}
          ${card(
            "Query params",
            `<ul>
              <li><code>period</code>: <code>day</code> | <code>range</code></li>
              <li><code>day</code>: YYYY-MM-DD (when period=day)</li>
              <li><code>date_from</code>, <code>date_to</code>: YYYY-MM-DD (when period=range)</li>
            </ul>
            ${codeBlock(
              esc,
              `curl "${base}/usage/summary?period=day&day=2026-07-18" \\
  -H "Authorization: Bearer $TOKEN"`,
              "ad-usage"
            )}`
          )}`,

        logs: () => `
          <h1>Request logs</h1>
          ${endpointBar(esc, "GET", "/request-logs", base)}
          ${card(
            "Filters",
            `<p>Query: <code>limit</code>, <code>offset</code>, <code>ip</code>, <code>method</code>, <code>status</code> (or <code>status_min</code>/<code>status_max</code>), <code>path</code>, <code>errors_only=true</code></p>`
          )}
          ${endpointBar(esc, "GET", "/request-logs/ip-summary?hours=24&limit=30", base)}
          ${endpointBar(esc, "GET", "/login-logs?limit=50", base)}`,

        security: () => `
          <h1>Ban IP / 2FA</h1>
          ${endpointBar(esc, "GET", "/banned-ips", base)}
          ${endpointBar(esc, "POST", "/banned-ips", base)}
          ${card(
            "Ban IP",
            `${codeBlock(
              esc,
              `curl -X POST ${base}/banned-ips \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"ip":"1.2.3.4","reason":"spam","source":"manual"}'`,
              "ad-ban"
            )}`
          )}
          ${endpointBar(esc, "DELETE", "/banned-ips/{ip}", base)}
          ${endpointBar(esc, "GET", "/2fa", base)}
          ${endpointBar(esc, "POST", "/2fa/generate", base)}
          <p>Generate rotates TOTP secret (returned once) for authenticator apps.</p>`,
      };

      const renderPage = pages[section] || pages.intro;
      main.innerHTML = renderPage();

      main.querySelectorAll("a[data-sec], .docs-side a[data-sec]").forEach(() => {});
      document.querySelectorAll(".docs-side a[data-sec]").forEach((a) => {
        a.classList.toggle("active", a.getAttribute("data-sec") === section);
      });

      document.querySelectorAll(".code-copy, .copy-btn").forEach((btn) => {
        btn.onclick = async () => {
          let text = btn.getAttribute("data-copy-text");
          if (!text && btn.dataset.copyId) {
            text = document.getElementById(btn.dataset.copyId)?.textContent || "";
          }
          try {
            await navigator.clipboard.writeText(text || "");
            const prev = btn.textContent;
            btn.textContent = "OK";
            setTimeout(() => {
              btn.textContent = prev;
            }, 1000);
          } catch (_) {}
        };
      });
    },
  };
})();
