(() => {
  function featured(t) {
    return [
      { id: "claude-fable-5", name: "Claude Fable 5", tip: t("docs.tip.fable5") },
      { id: "claude-opus-4-8", name: "Claude Opus 4.8", tip: t("docs.tip.opus48") },
      { id: "claude-opus-4-7", name: "Claude Opus 4.7", tip: t("docs.tip.opus47") },
      { id: "claude-sonnet-5", name: "Claude Sonnet 5", tip: t("docs.tip.sonnet5") },
      { id: "claude-opus-4-6", name: "Claude Opus 4.6", tip: t("docs.tip.opus46") },
      { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", tip: t("docs.tip.haiku") },
    ];
  }

  function baseUrl() {
    return `${location.origin}/api/v1`;
  }

  function codeBlock(esc, t, text, id) {
    return `<div class="code-block"><button class="btn btn-secondary btn-small code-copy" type="button" data-copy-id="${id}">${esc(t("common.copy"))}</button><pre id="${id}">${esc(text)}</pre></div>`;
  }

  function endpointBar(t, method, path) {
    const cls = method.toLowerCase();
    return `<div class="endpoint-bar">
      <span class="verb ${cls}">${method}</span>
      <span class="path">${path}</span>
      <button class="btn btn-secondary btn-small copy-btn" type="button" data-copy-text="${baseUrl()}${path}">${t("common.copyUrl")}</button>
    </div>`;
  }

  window.MrdevDocs = {
    render(app, opts) {
      const { esc, api, userKey } = opts;
      const t = opts.t || ((k, v) => (window.MrdevI18n ? window.MrdevI18n.t(k, v) : k));
      const keyValue = typeof userKey === "function" ? userKey() : userKey || "";
      document.body.classList.add("docs-mode");
      const section = (location.hash.split("/")[2] || "intro").toLowerCase();
      const base = baseUrl();
      const origin = location.origin.replace(/\/$/, "");
      const FEATURED = featured(t);

      app.innerHTML = `
        <div class="docs-shell">
          <aside class="docs-side">
            <div class="side-brand">
              <strong>${esc(t("docs.brand"))}</strong>
              <small>${esc(t("docs.brandSub"))}</small>
            </div>
            <div class="docs-base">${esc(base)}</div>
            <div class="docs-group">
              <h4>${esc(t("docs.group.start"))}</h4>
              <a href="#/docs/intro" data-sec="intro">${esc(t("docs.nav.intro"))}</a>
              <a href="#/docs/auth" data-sec="auth">${esc(t("docs.nav.auth"))}</a>
              <a href="#/docs/models-list" data-sec="models-list">${esc(t("docs.nav.modelsList"))}</a>
            </div>
            <div class="docs-group">
              <h4>${esc(t("docs.group.clients"))}</h4>
              <a href="#/docs/cursor" data-sec="cursor">${esc(t("docs.nav.cursor"))}</a>
              <a href="#/docs/antigravity" data-sec="antigravity">${esc(t("docs.nav.antigravity"))}</a>
              <a href="#/docs/claude-code" data-sec="claude-code">${esc(t("docs.nav.claudeCode"))}</a>
              <a href="#/docs/vscode" data-sec="vscode">${esc(t("docs.nav.vscode"))}</a>
              <a href="#/docs/sub2api" data-sec="sub2api">${esc(t("docs.nav.sub2api"))}</a>
              <a href="#/docs/openai-sdk" data-sec="openai-sdk">${esc(t("docs.nav.openaiSdk"))}</a>
            </div>
            <div class="docs-group">
              <h4>${esc(t("docs.group.api"))}</h4>
              <a href="#/docs/models" data-sec="models"><span class="method get">GET</span> ${esc(t("docs.nav.models"))}</a>
              <a href="#/docs/chat" data-sec="chat"><span class="method post">POST</span> ${esc(t("docs.nav.chat"))}</a>
              <a href="#/docs/messages" data-sec="messages"><span class="method post">POST</span> ${esc(t("docs.nav.messages"))}</a>
              <a href="#/docs/responses" data-sec="responses"><span class="method post">POST</span> ${esc(t("docs.nav.responses"))}</a>
              <a href="#/docs/embeddings" data-sec="embeddings"><span class="method post">POST</span> ${esc(t("docs.nav.embeddings"))}</a>
              <a href="#/docs/me" data-sec="me"><span class="method get">GET</span> ${esc(t("docs.nav.me"))}</a>
              <a href="#/docs/redeem" data-sec="redeem"><span class="method post">POST</span> ${esc(t("docs.nav.redeem"))}</a>
            </div>
          </aside>
          <div class="docs-main" id="docs-main"></div>
        </div>`;

      const main = document.getElementById("docs-main");
      const pages = {
        intro: () => `
          <div class="docs-hero">
            <div>
              <h1>${esc(t("docs.intro.title"))}</h1>
              <p class="lead">${esc(t("docs.intro.lead"))}</p>
            </div>
            <div class="docs-badges">
              <span class="ok">OpenAI compatible</span>
              <span class="ok">Anthropic /v1/messages</span>
              <span>SSE streaming</span>
              <span>CDK redeem</span>
            </div>
          </div>
          <div class="docs-card accent">
            <h3>${esc(t("docs.intro.quick"))}</h3>
            <div class="flow-steps">
              <div class="flow-step"><div class="n">01</div><p>${esc(t("docs.intro.s1"))}</p></div>
              <div class="flow-step"><div class="n">02</div><p>${esc(t("docs.intro.s2"))}</p></div>
              <div class="flow-step"><div class="n">03</div><p>${esc(t("docs.intro.s3", { base }))}</p></div>
              <div class="flow-step"><div class="n">04</div><p>${esc(t("docs.intro.s4"))}</p></div>
            </div>
          </div>
          <div class="docs-grid">
            <div class="docs-card">
              <h3>${esc(t("docs.intro.cfg"))}</h3>
              ${codeBlock(
                esc,
                t,
                `# OpenAI-compatible
OPENAI_BASE_URL=${base}
OPENAI_API_KEY=bag_xxxxxxxx_your_secret

# Anthropic Messages (Claude Code / SDK)
ANTHROPIC_BASE_URL=${origin}
ANTHROPIC_API_KEY=bag_xxxxxxxx_your_secret`,
                "cfg-env"
              )}
            </div>
            <div class="docs-card">
              <h3>${esc(t("docs.intro.test"))}</h3>
              ${codeBlock(
                esc,
                t,
                `curl ${base}/models \\
  -H "Authorization: Bearer bag_xxxxxxxx"

curl ${origin}/v1/messages \\
  -H "x-api-key: bag_xxxxxxxx" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "content-type: application/json" \\
  -d '{"model":"claude-opus-4-6","max_tokens":64,"messages":[{"role":"user","content":"hi"}]}'`,
                "cfg-test"
              )}
            </div>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.intro.flow"))}</h3>
            <ol>
              <li>${esc(t("docs.intro.li1"))}</li>
              <li>${esc(t("docs.intro.li2"))}</li>
              <li>${esc(t("docs.intro.li3"))}</li>
              <li>${esc(t("docs.intro.li4"))}</li>
            </ol>
          </div>`,

        auth: () => `
          <h1>${esc(t("docs.auth.title"))}</h1>
          <p class="lead">${esc(t("docs.auth.lead"))}</p>
          ${endpointBar(t, "POST", "/redeem")}
          <div class="docs-card">
            <h3>${esc(t("docs.auth.headers"))}</h3>
            <table class="param-table">
              <thead><tr><th>${esc(t("docs.col.name"))}</th><th>${esc(t("docs.col.required"))}</th><th>${esc(t("docs.col.example"))}</th></tr></thead>
              <tbody>
                <tr><td><code>Authorization</code></td><td>${esc(t("docs.auth.orKey"))}</td><td><code>Bearer bag_...</code></td></tr>
                <tr><td><code>x-api-key</code></td><td>${esc(t("docs.auth.orKey"))}</td><td><code>bag_...</code></td></tr>
                <tr><td><code>anthropic-version</code></td><td>${esc(t("docs.auth.optionalAnt"))}</td><td><code>2023-06-01</code></td></tr>
                <tr><td><code>Content-Type</code></td><td>${esc(t("docs.yesPost"))}</td><td><code>application/json</code></td></tr>
              </tbody>
            </table>
            <p class="sub">${esc(t("docs.auth.pickOne"))}</p>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.auth.getKey"))}</h3>
            <ul>
              <li>${esc(t("docs.auth.li1"))}</li>
              <li>${esc(t("docs.auth.li2"))}</li>
            </ul>
            <p>${esc(t("docs.auth.codes"))}</p>
          </div>`,

        "models-list": () => `
          <h1>${esc(t("docs.modelsList.title"))}</h1>
          <p class="lead">${esc(t("docs.modelsList.lead"))}</p>
          <div class="docs-toolbar">
            <input id="docs-key" type="password" placeholder="${esc(t("docs.modelsList.placeholder"))}" value="${esc(keyValue)}" />
            <button class="btn btn-primary" id="docs-load-models" type="button">${esc(t("docs.modelsList.load"))}</button>
          </div>
          <div id="docs-models-alert"></div>
          <h3 style="font-family:var(--display);margin:0 0 0.75rem">${esc(t("docs.modelsList.recommended"))}</h3>
          <div class="model-grid" id="featured-models">
            ${FEATURED.map(
              (m) => `<div class="model-chip"><strong>${esc(m.name)}</strong><code>${esc(m.id)}</code><div class="hint">${esc(m.tip)}</div></div>`
            ).join("")}
          </div>
          <h3 style="font-family:var(--display);margin:1.25rem 0 0.75rem">${esc(t("docs.modelsList.all"))} <span id="model-count" style="color:var(--muted);font-size:0.9rem"></span></h3>
          <div class="model-grid" id="live-models"><div class="empty" style="grid-column:1/-1">${esc(t("docs.modelsList.empty"))}</div></div>`,

        cursor: () => `
          <h1>${esc(t("docs.cursor.title"))}</h1>
          <p class="lead">${esc(t("docs.cursor.lead"))}</p>
          <div class="docs-card">
            <h3>${esc(t("docs.cursor.how"))}</h3>
            <ol>
              <li>${esc(t("docs.cursor.li1"))}</li>
              <li>${esc(t("docs.cursor.li2"))}</li>
              <li>${esc(t("docs.cursor.li3"))}</li>
              <li>${esc(t("docs.cursor.li4", { base }))}</li>
              <li>${esc(t("docs.cursor.li5"))}</li>
            </ol>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cursor.suggest"))}</h3>
            ${codeBlock(
              esc,
              t,
              `OpenAI API Key: bag_xxxxxxxx
Override OpenAI Base URL: ${base}
Model IDs:
  claude-opus-4-8
  claude-opus-4-6
  claude-fable-5
  claude-sonnet-4-5`,
              "cursor-cfg"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cursor.notes"))}</h3>
            <ul>
              <li>${esc(t("docs.cursor.n1"))}</li>
              <li>${esc(t("docs.cursor.n2"))}</li>
              <li>${esc(t("docs.cursor.n3"))}</li>
            </ul>
          </div>`,

        antigravity: () => `
          <h1>${esc(t("docs.ag.title"))}</h1>
          <p class="lead">${esc(t("docs.ag.lead"))}</p>
          <div class="docs-card">
            <h3>${esc(t("docs.ag.how"))}</h3>
            <ol>
              <li>${esc(t("docs.ag.li1"))}</li>
              <li>${esc(t("docs.ag.li2"))}</li>
              <li>${esc(t("docs.ag.li3"))}</li>
              <li>${esc(t("docs.ag.li4", { base }))}</li>
              <li>${esc(t("docs.ag.li5"))}</li>
              <li>${esc(t("docs.ag.li6"))}</li>
            </ol>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.ag.cfg"))}</h3>
            <p class="sub">${esc(t("docs.ag.cfgHint"))}</p>
            ${codeBlock(
              esc,
              t,
              `[
  {
    "name": "models/claude-opus-4-6",
    "displayName": "Claude Opus 4.6 (MRDEV)",
    "description": "via MRDEV Gateway",
    "provider": "custom",
    "apiKey": "bag_xxxxxxxx",
    "apiUrl": "${base}",
    "externalModelName": "claude-opus-4-6"
  },
  {
    "name": "models/claude-opus-4-8",
    "displayName": "Claude Opus 4.8 (MRDEV)",
    "description": "via MRDEV Gateway",
    "provider": "custom",
    "apiKey": "bag_xxxxxxxx",
    "apiUrl": "${base}",
    "externalModelName": "claude-opus-4-8"
  },
  {
    "name": "models/claude-fable-5",
    "displayName": "Claude Fable 5 (MRDEV)",
    "description": "via MRDEV Gateway",
    "provider": "custom",
    "apiKey": "bag_xxxxxxxx",
    "apiUrl": "${base}",
    "externalModelName": "claude-fable-5"
  }
]`,
              "ag-cfg"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.ag.quick"))}</h3>
            ${codeBlock(
              esc,
              t,
              `Provider:  custom (OpenAI-compatible)
API URL:   ${base}
API Key:   bag_xxxxxxxx
Model:     claude-opus-4-6   (or claude-opus-4-8 / claude-fable-5)

# Windows config file:
%USERPROFILE%\\.gemini\\antigravity\\custom_models.json`,
              "ag-quick"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.ag.notes"))}</h3>
            <ul>
              <li>${esc(t("docs.ag.n1"))}</li>
              <li>${esc(t("docs.ag.n2", { base }))}</li>
              <li>${esc(t("docs.ag.n3"))}</li>
              <li>${esc(t("docs.ag.n4"))}</li>
            </ul>
          </div>`,

        "claude-code": () => `
          <h1>${esc(t("docs.cc.title"))}</h1>
          <p class="lead">${esc(t("docs.cc.lead"))}</p>
          <div class="docs-card">
            <h3>${esc(t("docs.cc.direct"))}</h3>
            ${codeBlock(
              esc,
              t,
              `# PowerShell
$env:ANTHROPIC_BASE_URL = "${origin}"
$env:ANTHROPIC_API_KEY = "bag_xxxxxxxx"
claude

# curl
curl ${origin}/v1/messages \\
  -H "x-api-key: bag_xxxxxxxx" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "content-type: application/json" \\
  -d '{"model":"claude-opus-4-6","max_tokens":256,"messages":[{"role":"user","content":"hi"}]}'`,
              "cc-direct"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cc.install"))}</h3>
            <p>${esc(t("docs.cc.installHint"))}</p>
            ${codeBlock(
              esc,
              t,
              `npm install -g @anthropic-ai/claude-code
# optional router
npm install -g @musistudio/claude-code-router`,
              "cc-install"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cc.config"))}</h3>
            <p>${esc(t("docs.cc.configHint"))}</p>
            <p>${esc(t("docs.cc.windows"))}</p>
            ${codeBlock(
              esc,
              t,
              `{
  "Providers": [
    {
      "name": "mrdev",
      "api_base_url": "${base}/chat/completions",
      "api_key": "bag_xxxxxxxx",
      "models": [
        "claude-opus-4-8",
        "claude-opus-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5"
      ]
    }
  ],
  "Router": {
    "default": "mrdev,claude-opus-4-6",
    "background": "mrdev,claude-haiku-4-5",
    "think": "mrdev,claude-opus-4-8"
  }
}`,
              "cc-config"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cc.run"))}</h3>
            ${codeBlock(
              esc,
              t,
              `# Use 'ccr code' instead of 'claude'
ccr code

# or run in a project folder
cd my-project
ccr code`,
              "cc-run"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.cc.notes"))}</h3>
            <ol>
              <li>${esc(t("docs.cc.n1"))}</li>
              <li>${esc(t("docs.cc.n2"))}</li>
              <li>${esc(t("docs.cc.n3", { base }))}</li>
              <li>${esc(t("docs.cc.n4", { base, origin }))}</li>
            </ol>
          </div>`,

        vscode: () => `
          <h1>${esc(t("docs.vscode.title"))}</h1>
          <p class="lead">${esc(t("docs.vscode.lead"))}</p>
          <div class="docs-card">
            <h3>${esc(t("docs.vscode.continue"))}</h3>
            ${codeBlock(
              esc,
              t,
              `{
  "models": [
    {
      "title": "MRDEV Opus 4.6",
      "provider": "openai",
      "model": "claude-opus-4-6",
      "apiBase": "${base}",
      "apiKey": "bag_xxxxxxxx"
    }
  ]
}`,
              "vscode-continue"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.vscode.rest"))}</h3>
            ${codeBlock(
              esc,
              t,
              `POST ${base}/chat/completions
Authorization: Bearer bag_xxxxxxxx
Content-Type: application/json

{
  "model": "claude-opus-4-6",
  "messages": [{"role":"user","content":"Hello"}]
}`,
              "vscode-rest"
            )}
          </div>`,

        sub2api: () => `
          <h1>${esc(t("docs.sub2api.title"))}</h1>
          <p class="lead">${esc(t("docs.sub2api.lead"))}</p>
          <div class="docs-card">
            <h3>${esc(t("docs.sub2api.how"))}</h3>
            <ol>
              <li>${esc(t("docs.sub2api.li1"))}</li>
              <li>${esc(t("docs.sub2api.li2"))}</li>
              <li>${esc(t("docs.sub2api.li3", { base }))}</li>
              <li>${esc(t("docs.sub2api.li4"))}</li>
              <li>${esc(t("docs.sub2api.li5"))}</li>
              <li>${esc(t("docs.sub2api.li6"))}</li>
            </ol>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.sub2api.cfg"))}</h3>
            ${codeBlock(
              esc,
              t,
              `Platform / Type: OpenAI → API Key
Base URL: ${base}
API Key:  bag_xxxxxxxx_your_secret
Model:    claude-opus-4-6

# Optional (recommended if test fails with 404):
Responses mode: Force Chat Completions`,
              "sub2api-cfg"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.sub2api.mode"))}</h3>
            <p>${esc(t("docs.sub2api.modeBody"))}</p>
            ${codeBlock(
              esc,
              t,
              `# Sub2API default path:
POST ${base}/responses

# Or Chat Completions:
POST ${base}/chat/completions`,
              "sub2api-paths"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.sub2api.test"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/responses \\
  -H "Authorization: Bearer bag_xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-opus-4-6",
    "input": "hi"
  }'`,
              "sub2api-test"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.sub2api.notes"))}</h3>
            <ul>
              <li>${esc(t("docs.sub2api.n1"))}</li>
              <li>${esc(t("docs.sub2api.n2"))}</li>
              <li>${esc(t("docs.sub2api.n3"))}</li>
              <li>${esc(t("docs.sub2api.n4"))}</li>
            </ul>
          </div>`,

        responses: () => `
          <h1>${esc(t("docs.responses.title"))}</h1>
          <p class="lead">${esc(t("docs.responses.lead"))}</p>
          ${endpointBar(t, "POST", "/responses")}
          <div class="docs-card">
            <h3>${esc(t("docs.responses.why"))}</h3>
            <p>${esc(t("docs.responses.whyBody"))}</p>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.emb.ex"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/responses \\
  -H "Authorization: Bearer bag_xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-opus-4-6",
    "input": "Hello"
  }'`,
              "curl-responses"
            )}
          </div>`,

        "openai-sdk": () => `
          <h1>${esc(t("docs.sdk.title"))}</h1>
          <p class="lead">${esc(t("docs.sdk.lead"))}</p>
          <div class="docs-card">
            <h3>Python</h3>
            ${codeBlock(
              esc,
              t,
              `from openai import OpenAI

client = OpenAI(
    api_key="bag_xxxxxxxx",
    base_url="${base}",
)

r = client.chat.completions.create(
    model="claude-opus-4-6",
    messages=[{"role": "user", "content": "Hello"}],
)
print(r.choices[0].message.content)`,
              "sdk-py"
            )}
          </div>
          <div class="docs-card">
            <h3>Node.js</h3>
            ${codeBlock(
              esc,
              t,
              `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "bag_xxxxxxxx",
  baseURL: "${base}",
});

const r = await client.chat.completions.create({
  model: "claude-opus-4-6",
  messages: [{ role: "user", content: "Hello" }],
});
console.log(r.choices[0].message.content);`,
              "sdk-node"
            )}
          </div>`,

        models: () => `
          <h1>${esc(t("docs.models.title"))}</h1>
          <p class="lead">${esc(t("docs.models.lead"))}</p>
          ${endpointBar(t, "GET", "/models")}
          <div class="docs-card">
            <h3>cURL</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/models \\
  -H "Authorization: Bearer bag_xxxxxxxx"`,
              "curl-models"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.models.resp"))}</h3>
            ${codeBlock(
              esc,
              t,
              `{
  "object": "list",
  "data": [
    {"id": "claude-opus-4-6", "object": "model", "owned_by": "system"}
  ]
}`,
              "resp-models"
            )}
          </div>`,

        chat: () => `
          <h1>${esc(t("docs.chat.title"))}</h1>
          <p class="lead">${esc(t("docs.chat.lead"))}</p>
          ${endpointBar(t, "POST", "/chat/completions")}
          <div class="docs-card">
            <h3>${esc(t("docs.chat.params"))}</h3>
            <table class="param-table">
              <thead><tr><th>${esc(t("docs.chat.field"))}</th><th>${esc(t("docs.chat.type"))}</th><th>${esc(t("docs.chat.notes"))}</th></tr></thead>
              <tbody>
                <tr><td><code>model</code></td><td>string</td><td>Model ID (e.g. claude-opus-4-8)</td></tr>
                <tr><td><code>messages</code></td><td>array</td><td>system / user / assistant / tool</td></tr>
                <tr><td><code>stream</code></td><td>bool</td><td>SSE when <code>true</code></td></tr>
                <tr><td><code>max_tokens</code></td><td>int</td><td>${esc(t("docs.chat.maxNote"))}</td></tr>
                <tr><td><code>temperature</code></td><td>float</td><td>0–2</td></tr>
                <tr><td><code>tools</code></td><td>array</td><td>Tool calling</td></tr>
                <tr><td><code>reasoning_effort</code></td><td>string</td><td>low / medium / high</td></tr>
              </tbody>
            </table>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.chat.reqEx"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/chat/completions \\
  -H "Authorization: Bearer bag_xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-opus-4-6",
    "messages": [{"role":"user","content":"Hello"}],
    "max_tokens": 1024
  }'`,
              "curl-chat"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.chat.streaming"))}</h3>
            ${codeBlock(
              esc,
              t,
              `{
  "model": "claude-opus-4-6",
  "stream": true,
  "stream_options": {"include_usage": true},
  "messages": [{"role":"user","content":"Hello"}]
}`,
              "chat-stream"
            )}
          </div>`,

        messages: () => `
          <h1>${esc(t("docs.messages.title"))}</h1>
          <p class="lead">${esc(t("docs.messages.lead"))}</p>
          ${endpointBar(t, "POST", "/messages")}
          <div class="docs-card">
            <h3>${esc(t("docs.messages.paths"))}</h3>
            <ul>
              <li><code>POST ${origin}/v1/messages</code> — ${esc(t("docs.messages.pathV1"))}</li>
              <li><code>POST ${base}/messages</code> — ${esc(t("docs.messages.pathApi"))}</li>
            </ul>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.messages.params"))}</h3>
            <table class="param-table">
              <thead><tr><th>${esc(t("docs.chat.field"))}</th><th>${esc(t("docs.chat.type"))}</th><th>${esc(t("docs.chat.notes"))}</th></tr></thead>
              <tbody>
                <tr><td><code>model</code></td><td>string</td><td>${esc(t("docs.messages.modelNote"))}</td></tr>
                <tr><td><code>max_tokens</code></td><td>int</td><td>${esc(t("docs.messages.maxNote"))}</td></tr>
                <tr><td><code>system</code></td><td>string / array</td><td>${esc(t("docs.messages.systemNote"))}</td></tr>
                <tr><td><code>messages</code></td><td>array</td><td>user / assistant (+ tool_use / tool_result)</td></tr>
                <tr><td><code>stream</code></td><td>bool</td><td>${esc(t("docs.messages.streamNote"))}</td></tr>
                <tr><td><code>tools</code></td><td>array</td><td>name / description / input_schema</td></tr>
                <tr><td><code>tool_choice</code></td><td>object</td><td>auto / any / tool</td></tr>
                <tr><td><code>temperature</code></td><td>float</td><td>0–1 (Anthropic style)</td></tr>
              </tbody>
            </table>
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.chat.reqEx"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${origin}/v1/messages \\
  -H "x-api-key: bag_xxxxxxxx" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "content-type: application/json" \\
  -d '{
    "model": "claude-opus-4-6",
    "max_tokens": 1024,
    "system": "Be concise.",
    "messages": [{"role":"user","content":"Hello"}]
  }'`,
              "curl-messages"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.messages.streamTitle"))}</h3>
            <p>${esc(t("docs.messages.streamBody"))}</p>
            ${codeBlock(
              esc,
              t,
              `event: message_start
event: content_block_start
event: content_block_delta
event: content_block_stop
event: message_delta
event: message_stop`,
              "messages-sse"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.messages.claudeEnv"))}</h3>
            ${codeBlock(
              esc,
              t,
              `$env:ANTHROPIC_BASE_URL = "${origin}"
$env:ANTHROPIC_API_KEY = "bag_xxxxxxxx"
claude`,
              "messages-claude-env"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.messages.notes"))}</h3>
            <ul>
              <li>${esc(t("docs.messages.n1"))}</li>
              <li>${esc(t("docs.messages.n2"))}</li>
              <li>${esc(t("docs.messages.n3"))}</li>
              <li>${esc(t("docs.messages.n4"))}</li>
            </ul>
          </div>`,

        embeddings: () => `
          <h1>${esc(t("docs.emb.title"))}</h1>
          <p class="lead">${esc(t("docs.emb.lead"))}</p>
          ${endpointBar(t, "POST", "/embeddings")}
          <div class="docs-card">
            <h3>${esc(t("docs.emb.ex"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/embeddings \\
  -H "Authorization: Bearer bag_xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "embed-multilingual-v3",
    "input": ["xin chào"]
  }'`,
              "curl-emb"
            )}
          </div>`,

        me: () => `
          <h1>${esc(t("docs.me.title"))}</h1>
          <p class="lead">${esc(t("docs.me.lead"))}</p>
          ${endpointBar(t, "GET", "/me")}
          <div class="docs-card">
            <h3>${esc(t("docs.emb.ex"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/me -H "Authorization: Bearer bag_xxxxxxxx"`,
              "curl-me"
            )}
          </div>`,

        redeem: () => `
          <h1>${esc(t("docs.redeem.title"))}</h1>
          <p class="lead">${esc(t("docs.redeem.lead"))}</p>
          ${endpointBar(t, "POST", "/redeem")}
          <div class="docs-card">
            <h3>${esc(t("docs.emb.ex"))}</h3>
            ${codeBlock(
              esc,
              t,
              `curl ${base}/redeem \\
  -H "Content-Type: application/json" \\
  -d '{"cdk":"CDK-XXXX-XXXX-XXXX"}'`,
              "curl-redeem"
            )}
          </div>
          <div class="docs-card">
            <h3>${esc(t("docs.redeem.resp"))}</h3>
            ${codeBlock(
              esc,
              t,
              `{
  "api_key": "bag_...",
  "key_id": "...",
  "name": "user-......",
  "rpm_limit": 60,
  "monthly_token_quota": 2000000,
  "note": "Save the API key immediately. CDK is single-use."
}`,
              "resp-redeem"
            )}
          </div>`,
      };

      const renderPage = pages[section] || pages.intro;
      main.innerHTML = renderPage();

      document.querySelectorAll(".docs-group a").forEach((a) => {
        a.classList.toggle("active", a.dataset.sec === (pages[section] ? section : "intro"));
      });

      main.querySelectorAll("[data-copy-id]").forEach((btn) => {
        btn.onclick = async () => {
          const el = document.getElementById(btn.dataset.copyId);
          await navigator.clipboard.writeText(el?.innerText || "");
          btn.textContent = t("common.copied");
          setTimeout(() => (btn.textContent = t("common.copy")), 1200);
        };
      });
      main.querySelectorAll("[data-copy-text]").forEach((btn) => {
        btn.onclick = async () => {
          await navigator.clipboard.writeText(btn.dataset.copyText);
          btn.textContent = t("common.copied");
          setTimeout(() => (btn.textContent = t("common.copyUrl")), 1200);
        };
      });

      const loadBtn = document.getElementById("docs-load-models");
      if (loadBtn) {
        loadBtn.onclick = async () => {
          const key = document.getElementById("docs-key").value.trim();
          const alert = document.getElementById("docs-models-alert");
          const grid = document.getElementById("live-models");
          if (!key) {
            alert.innerHTML = `<div class="alert alert-warn">${esc(t("docs.modelsList.needKey"))}</div>`;
            return;
          }
          try {
            const data = await api("/models", { token: key });
            const ids = (data.data || []).map((m) => m.id);
            document.getElementById("model-count").textContent = `(${ids.length})`;
            grid.innerHTML = ids
              .map((id) => `<div class="model-chip"><code>${esc(id)}</code></div>`)
              .join("");
            alert.innerHTML = `<div class="alert alert-ok">${esc(t("docs.modelsList.loaded", { n: ids.length }))}</div>`;
          } catch (err) {
            alert.innerHTML = `<div class="alert alert-error">${esc(err.message)}</div>`;
          }
        };
      }
    },
  };
})();
