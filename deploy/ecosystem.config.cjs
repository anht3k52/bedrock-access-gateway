/**
 * PM2 process file for MRDEV Gateway + Cloudflare Tunnel.
 * Start:  deploy\start-pm2.bat
 * Stop:   deploy\stop-pm2.bat
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

function which(cmd) {
  try {
    const out = execSync(`where ${cmd}`, { encoding: "utf8" });
    return out
      .split(/\r?\n/)
      .map((s) => s.trim())
      .find(Boolean) || cmd;
  } catch {
    return cmd;
  }
}

function loadEnv(file) {
  const env = {};
  if (!fs.existsSync(file)) return env;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i < 0) continue;
    let v = t.slice(i + 1).trim();
    if (
      (v.startsWith('"') && v.endsWith('"')) ||
      (v.startsWith("'") && v.endsWith("'"))
    ) {
      v = v.slice(1, -1);
    }
    env[t.slice(0, i).trim()] = v;
  }
  return env;
}

const deployDir = __dirname;
const repoRoot = path.dirname(deployDir);
const envLocal = loadEnv(path.join(deployDir, ".env.local"));
const host = envLocal.HOST || "127.0.0.1";
const port = String(envLocal.PORT || "8000");
const python = which("python");
const cloudflared = which("cloudflared");
const tunnelConfig = path.join(deployDir, "cloudflared-config.yml");

module.exports = {
  apps: [
    {
      name: "mrdev-gateway",
      cwd: path.join(repoRoot, "src"),
      script: python,
      args: `-m uvicorn api.app:app --host ${host} --port ${port} --timeout-keep-alive 30 --limit-concurrency 100`,
      interpreter: "none",
      autorestart: true,
      max_restarts: 100,
      min_uptime: "5s",
      restart_delay: 2000,
      kill_timeout: 8000,
      env: {
        ...envLocal,
        HOST: host,
        PORT: port,
        AWS_REGION: envLocal.AWS_REGION || "us-west-2",
        AWS_DEFAULT_REGION:
          envLocal.AWS_DEFAULT_REGION || envLocal.AWS_REGION || "us-west-2",
      },
    },
    {
      name: "mrdev-tunnel",
      cwd: repoRoot,
      script: cloudflared,
      args: `tunnel --config "${tunnelConfig}" run`,
      interpreter: "none",
      autorestart: true,
      max_restarts: 100,
      min_uptime: "5s",
      restart_delay: 3000,
      kill_timeout: 8000,
    },
  ],
};
