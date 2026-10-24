#!/usr/bin/env node
// guarddog-mcp: npx入口。策略: uvx优先(uv生态) -> python3直跑(共享安装)。
// 错误按十诫第6条: 自解释+可执行hint。
const { spawnSync, spawn } = require("child_process");
const path = require("path");
const os = require("os");
const fs = require("fs");

const LIB = path.join(__dirname, "..", "lib");
const VENV = path.join(os.homedir(), ".guarddog-mcp", "venv");

function die(err, hint) {
  console.error(JSON.stringify({ error: err, hint: hint }));
  process.exit(1);
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

// 首次运行: 建共享venv装依赖(约30-60s, 之后秒起)
function ensureVenv() {
  const py = VENV + "/bin/python";
  if (fs.existsSync(py)) return py;
  const python3 = pickPython();
  if (!python3) die("python_3_10_not_found",
    "install Python 3.10+ (macOS: brew install python@3.12; ubuntu: apt install python3.12) then re-run npx guarddog-mcp");
  fs.mkdirSync(path.dirname(VENV), { recursive: true });
  console.error("[guarddog-mcp] first run: preparing environment (~30-60s)...");
  let r = spawnSync(python3, ["-m", "venv", VENV], { stdio: "inherit" });
  if (r.status !== 0) die("venv_create_failed", "run: python3 -m venv " + VENV);
  r = spawnSync(py, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check",
    "mcp>=2.3", "httpx", "redis", "asyncpg", "pydantic-settings"], { stdio: "inherit" });
  if (r.status !== 0) die("pip_install_failed",
    "run: " + py + " -m pip install mcp httpx redis asyncpg pydantic-settings");
  return py;
}

const py = ensureVenv();
// lib加入PYTHONPATH后启动MCP server (stdio)
const child = spawn(py, ["-m", "atg.mcp_server.server"], {
  env: Object.assign({}, process.env, { PYTHONPATH: LIB }),
  stdio: ["inherit", "inherit", "inherit"],
});
child.on("exit", (code) => process.exit(code || 0));
