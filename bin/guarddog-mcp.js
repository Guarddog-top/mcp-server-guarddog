#!/usr/bin/env node
// guarddog-mcp v1.0.1 npx入口
// - --smoke: 3秒零依赖实测(纯Node, 无需Python) — 装完即可验证
// - 信标: 安装漏斗遥测走 /v1/health?beacon=...(nginx落日志, 不依赖服务端改动)
// - MCP模式: 共享venv, 仅装 mcp+httpx (~10s), 检查直连云端API
const { spawnSync, spawn } = require("child_process");
const path = require("path");
const os = require("os");
const fs = require("fs");

const VERSION = "1.0.1";
const API = "https://api.guarddog.top";
const SMOKE_TARGET = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"; // WETH(eth) 规范冒烟目标
const LIB = path.join(__dirname, "..", "lib");
const VENV = path.join(os.homedir(), ".guarddog-mcp", "venv");

// ── 漏斗信标: fire-and-forget, 永不抛错, 永不阻塞主流程 ──
function beacon(stage, err) {
  try {
    const q = new URLSearchParams({ beacon: "guarddog-mcp", v: VERSION, stage: stage });
    if (err) q.set("err", String(err).slice(0, 64));
    fetch(API + "/v1/health?" + q.toString(),
          { headers: { "User-Agent": "guarddog-mcp/" + VERSION } })
      .catch(function () {});
  } catch (e) { /* 信标失败无所谓 */ }
}

function die(err, hint, stage) {
  console.error(JSON.stringify({ error: err, hint: hint }));
  beacon(stage || "error", err);
  setTimeout(function () { process.exit(1); }, 400); // 等信标飞出去
}

// ── --smoke: 纯Node直连云端API, 验证安装+网络+额度, 不碰Python ──
async function smoke() {
  const t0 = Date.now();
  try {
    const r = await fetch(API + "/v1/check?chain=eth&target=" + SMOKE_TARGET,
      { headers: { "User-Agent": "guarddog-mcp-smoke/" + VERSION } });
    const j = await r.json();
    if (!r.ok) {
      console.error("SMOKE_FAIL http " + r.status + ": " + JSON.stringify(j).slice(0, 200));
      beacon("smoke", "http_" + r.status);
      process.exit(1);
    }
    const v = j.verdict === "BLOCK" ? "BITE!" : j.verdict;
    console.log("🐕 GuardDog SMOKE " + v + " — WETH on eth | risk_score=" + j.risk_score +
                " | " + (Date.now() - t0) + "ms" + (j.data_limited ? " | data_limited" : ""));
    console.log("✅ install verified. Next: add guarddog to your MCP client (README → Install).");
    beacon("smoke_ok");
    process.exit(0);
  } catch (e) {
    console.error("SMOKE_FAIL network: " + e.message + " — check connectivity to " + API);
    beacon("smoke", "network");
    process.exit(1);
  }
}

function has(bin) {
  const r = spawnSync("which", [bin], { encoding: "utf8" });
  return r.status === 0;
}

// 选>=3.10解释器(mcp SDK要求; macOS系统python3=3.9不可用)
function pickPython() {
  const candidates = ["python3.13", "python3.12", "python3.11", "python3.10", "python3"];
  for (const c of candidates) {
    if (!has(c)) continue;
    const r = spawnSync(c, ["-c", "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)"]);
    if (r.status === 0) return c;
  }
  return null;
}

// 首次运行: 建共享venv(v1.0.1起只装mcp+httpx, ~10s; 旧版60s因为背了PG/redis)
function ensureVenv() {
  const py = VENV + "/bin/python";
  if (fs.existsSync(py)) return py;
  const python3 = pickPython();
  if (!python3) die("python_3_10_not_found",
    "install Python 3.10+ (macOS: brew install python@3.12; ubuntu: apt install python3.12) then re-run npx guarddog-mcp — or try: npx guarddog-mcp --smoke (no Python needed)",
    "python_missing");
  fs.mkdirSync(path.dirname(VENV), { recursive: true });
  console.error("[guarddog-mcp] first run: preparing environment (~10s)...");
  let r = spawnSync(python3, ["-m", "venv", VENV], { stdio: "inherit" });
  if (r.status !== 0) die("venv_create_failed", "run: python3 -m venv " + VENV, "venv_fail");
  r = spawnSync(py, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check",
    "mcp>=2.3", "httpx"], { stdio: "inherit" });
  if (r.status !== 0) die("pip_install_failed",
    "run: " + py + " -m pip install 'mcp>=2.3' httpx", "pip_fail");
  return py;
}

// ── 入口 ──
if (process.argv.includes("--smoke")) {
  smoke();
} else {
  const py = ensureVenv();
  // lib加入PYTHONPATH后启动MCP server (stdio) — server直连云端API
  const child = spawn(py, ["-m", "atg.mcp_server.server"], {
    env: Object.assign({}, process.env, { PYTHONPATH: LIB }),
    stdio: ["inherit", "inherit", "inherit"],
  });
  beacon("activated"); // venv就绪+进程拉起 = 激活成功信号
  child.on("exit", (code) => process.exit(code || 0));
}
