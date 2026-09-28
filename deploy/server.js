/**
 * AI 日报看板 · 静态文件服务 + 手动刷新（端口 5190）
 *
 * 设计原则：
 *   - 零外部依赖，只用 Node 内置模块（服务器已有 Node 22，无需 npm install）
 *   - 默认只读；仅在收到 /api/refresh 时才调 cli.py 重新抓取
 *   - 单进程、可随时重启
 *   - 默认拒绝目录穿越；只暴露 DATA_DIR 下的文件
 *
 * 路由：
 *   /             -> data/latest.html
 *   /latest.html  -> data/latest.html
 *   /<file>       -> data/<file>（限白名单扩展名）
 *   /healthz      -> {"ok":true,...}         探活
 *   /api/status   -> 当前刷新状态（前端轮询用）
 *   /api/refresh  -> POST 触发一次抓取更新；带冷却保护
 *
 * 启动：node server.js [--port 5190] [--root <data目录>] [--py <python.exe>] [--cooldown 60]
 */
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

// ---------------------------------------------------------------- 参数解析
// 注意：用「有没有下一个 argv」判断，而不是「下一个 argv 是不是 truthy」——
// 否则 `--cli ""` 这种「显式传空」会被当成「没传」，静默退回默认值。
function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  if (i !== -1 && i + 1 < process.argv.length) {
    const v = process.argv[i + 1];
    // 下一个仍然是 --xxx 说明本参数没带值（如 `--cli --port 8080`），按未传处理
    if (typeof v === 'string' && !v.startsWith('--')) return v;
    if (v === '') return '';
  }
  return fallback;
}

const PORT = parseInt(arg('port', process.env.BRIEFING_PORT || '5190'), 10);
const ROOT = path.resolve(arg('root', process.env.BRIEFING_ROOT || path.join(__dirname, 'data')));

// venv 里的 python（用于重新抓取）。默认在 ROOT 的上一级找 venv。
const APP_DIR = path.dirname(ROOT);
const PY = path.resolve(arg('py', process.env.BRIEFING_PY || path.join(APP_DIR, 'venv', 'Scripts', 'python.exe')));
const CLI_ARG = arg('cli', process.env.BRIEFING_CLI || path.join(APP_DIR, 'cli.py'));
// --cli 传空字符串表示「py 本身就是可执行程序」（如 PyInstaller 打的 exe），无需脚本参数
const CLI = CLI_ARG && CLI_ARG.trim() ? path.resolve(CLI_ARG) : '';

// 冷却秒数：距离上次刷新不足这个时间，拒绝再次触发（保护服务器）
const COOLDOWN = parseInt(arg('cooldown', process.env.BRIEFING_COOLDOWN || '60'), 10);

// 单次刷新最长执行时间，防止进程卡死
const REFRESH_TIMEOUT_MS = 5 * 60 * 1000;

// 只允许这些扩展名，避免误暴露 .cmd / .py / 备份文件
const ALLOWED_EXT = new Set(['.html', '.json', '.svg', '.png', '.ico', '.css', '.js']);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
};

// ---------------------------------------------------------------- 刷新状态
/**
 * 全局单例状态。同一时刻只允许一个刷新在跑。
 *   idle     空闲
 *   running  正在抓取
 *   ok       上次成功
 *   error    上次失败
 */
const refresh = {
  state: 'idle',
  startedAt: null,
  finishedAt: null,
  message: '',
  lastError: '',
  lastOkAt: null,
};

let refreshing = false;

/** 距离上次成功刷新过了多少秒；从未刷新返回 Infinity。 */
function secondsSinceLastOk() {
  if (!refresh.lastOkAt) return Infinity;
  return (Date.now() - refresh.lastOkAt) / 1000;
}

/**
 * 执行一次抓取更新：调 cli.py，等它跑完。
 * 完成后刷新状态。绝不抛异常（内部全捕获）。
 */
function runRefresh(trigger) {
  if (refreshing) return { accepted: false, reason: 'busy' };

  const since = secondsSinceLastOk();
  if (since < COOLDOWN) {
    return {
      accepted: false,
      reason: 'cooldown',
      retryAfter: Math.ceil(COOLDOWN - since),
    };
  }

  if (!fs.existsSync(PY)) {
    return { accepted: false, reason: 'no-python', detail: PY };
  }
  if (CLI && !fs.existsSync(CLI)) {
    return { accepted: false, reason: 'no-cli', detail: CLI };
  }

  refreshing = true;
  refresh.state = 'running';
  refresh.startedAt = new Date().toISOString();
  refresh.message = '正在抓取最新资讯...';
  refresh.lastError = '';

  console.log(`[i] 开始刷新（触发源: ${trigger}）`);

  // 两种调用形态：
  //   CLI 非空 -> <py> <cli> --out ...        （venv + 脚本）
  //   CLI 为空 -> <py> --out ...              （单文件 exe）
  const spawnArgs = CLI
    ? [CLI, '--out', ROOT, '--hours', '48', '--keep-days', '30']
    : ['--out', ROOT, '--hours', '48', '--keep-days', '30'];

  let child;
  try {
    child = spawn(PY, spawnArgs, {
      cwd: APP_DIR,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
  } catch (e) {
    refreshing = false;
    refresh.state = 'error';
    refresh.lastError = `启动失败: ${e.message}`;
    refresh.finishedAt = new Date().toISOString();
    console.error(`[x] 启动抓取失败: ${e.message}`);
    return { accepted: false, reason: 'spawn-failed', detail: e.message };
  }

  let out = '';
  const collect = (buf) => {
    out += buf.toString('utf-8');
    if (out.length > 20000) out = out.slice(-20000);   // 防无限增长
  };
  child.stdout.on('data', collect);
  child.stderr.on('data', collect);

  // 超时保护：卡太久就杀掉
  const timer = setTimeout(() => {
    console.warn('[!] 刷新超时，终止子进程');
    try { child.kill(); } catch { /* ignore */ }
  }, REFRESH_TIMEOUT_MS);

  child.on('error', (e) => {
    clearTimeout(timer);
    refreshing = false;
    refresh.state = 'error';
    refresh.lastError = e.message;
    refresh.finishedAt = new Date().toISOString();
    console.error(`[x] 刷新进程异常: ${e.message}`);
  });

  child.on('close', (code) => {
    clearTimeout(timer);
    refreshing = false;
    refresh.finishedAt = new Date().toISOString();

    if (code === 0) {
      refresh.state = 'ok';
      refresh.message = '已更新';
      refresh.lastOkAt = Date.now();
      console.log('[v] 刷新成功');
    } else {
      refresh.state = 'error';
      refresh.lastError = `退出码 ${code}`;
      refresh.message = '刷新失败';
      console.error(`[x] 刷新失败（退出码 ${code}）`);
      console.error(out.split('\n').slice(-15).join('\n'));   // 只记尾部
    }
  });

  return { accepted: true };
}

// ---------------------------------------------------------------- 工具
function send(res, code, body, headers = {}) {
  res.writeHead(code, {
    'Cache-Control': 'no-store',          // 看板每天更新，禁缓存保证拿到最新
    'X-Content-Type-Options': 'nosniff',
    ...headers,
  });
  res.end(body);
}

/** 把 URL 路径安全地解析到 ROOT 下的绝对路径；越界返回 null。 */
function resolveSafe(urlPath) {
  // 去掉 query / hash，解码
  let p;
  try {
    p = decodeURIComponent(urlPath.split('?')[0].split('#')[0]);
  } catch {
    return null;
  }
  if (p === '/' || p === '') p = '/latest.html';

  // 1) 拒绝任何 .. 片段（在解码后判断，防 %2e%2e 绕过）
  if (p.split('/').includes('..')) return null;

  const abs = path.resolve(ROOT, '.' + p);

  // 2) 必须仍在 ROOT 内（双保险）
  const rel = path.relative(ROOT, abs);
  if (rel.startsWith('..') || path.isAbsolute(rel)) return null;

  // 3) 扩展名白名单
  if (!ALLOWED_EXT.has(path.extname(abs).toLowerCase())) return null;

  return abs;
}

// ---------------------------------------------------------------- 服务
const server = http.createServer((req, res) => {
  const t0 = Date.now();
  const urlPath = (req.url || '/').split('?')[0];

  // ---- 刷新接口：POST /api/refresh ----
  if (urlPath === '/api/refresh') {
    if (req.method !== 'POST') {
      return send(res, 405, JSON.stringify({ ok: false, error: '请用 POST' }),
        { 'Content-Type': 'application/json; charset=utf-8' });
    }
    const r = runRefresh(req.headers['x-forwarded-for'] || req.socket.remoteAddress || 'local');
    if (r.accepted) {
      return send(res, 202, JSON.stringify({ ok: true, state: 'running' }),
        { 'Content-Type': 'application/json; charset=utf-8' });
    }
    const code = r.reason === 'busy' || r.reason === 'cooldown' ? 429 : 500;
    return send(res, code, JSON.stringify({ ok: false, ...r }),
      { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // ---- 状态接口：GET /api/status ----
  if (urlPath === '/api/status') {
    const latest = path.join(ROOT, 'latest.html');
    let dataTime = null;
    try {
      if (fs.existsSync(latest)) dataTime = fs.statSync(latest).mtime.toISOString();
    } catch { /* ignore */ }
    return send(res, 200, JSON.stringify({
      ok: true,
      ...refresh,
      cooldown: COOLDOWN,
      retryAfter: Math.max(0, Math.ceil(COOLDOWN - secondsSinceLastOk())),
      dataTime,
    }, null, 2), { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // 其余只接受 GET / HEAD
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    return send(res, 405, 'Method Not Allowed', { 'Content-Type': 'text/plain; charset=utf-8' });
  }

  // 探活端点
  if (urlPath === '/healthz') {
    const latest = path.join(ROOT, 'latest.html');
    const stat = fs.existsSync(latest) ? fs.statSync(latest) : null;
    return send(res, 200, JSON.stringify({
      ok: true,
      port: PORT,
      root: ROOT,
      latestHtml: stat ? { size: stat.size, mtime: stat.mtime.toISOString() } : null,
    }, null, 2), { 'Content-Type': 'application/json; charset=utf-8' });
  }

  const abs = resolveSafe(urlPath);
  if (!abs) {
    return send(res, 404, '404 Not Found', { 'Content-Type': 'text/plain; charset=utf-8' });
  }

  fs.readFile(abs, (err, buf) => {
    if (err) {
      const code = err.code === 'ENOENT' ? 404 : 500;
      return send(res, code, code === 404 ? '404 Not Found' : '500 Internal Error',
        { 'Content-Type': 'text/plain; charset=utf-8' });
    }
    const type = MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream';
    res.writeHead(200, {
      'Content-Type': type,
      'Content-Length': buf.length,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    if (req.method === 'HEAD') return res.end();
    res.end(buf);
    console.log(`[200] ${urlPath} -> ${path.basename(abs)} (${buf.length}B, ${Date.now() - t0}ms)`);
  });
});

server.on('error', (e) => {
  console.error(`[x] 服务启动失败: ${e.code} ${e.message}`);
  if (e.code === 'EADDRINUSE') {
    console.error(`    端口 ${PORT} 已被占用。换端口：node server.js --port 5191`);
  }
  process.exit(1);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[v] AI 日报看板服务已启动`);
  console.log(`    地址: http://127.0.0.1:${PORT}`);
  console.log(`    根目录: ${ROOT}`);
  console.log(`    探活: http://127.0.0.1:${PORT}/healthz`);
  console.log(`    刷新: POST http://127.0.0.1:${PORT}/api/refresh  (冷却 ${COOLDOWN}s)`);
  if (fs.existsSync(PY)) {
    console.log(`    抓取器: ${PY}${CLI ? ' + ' + path.basename(CLI) : '（单文件模式）'}`);
  } else {
    console.warn(`[!] 找不到抓取器: ${PY}`);
    console.warn(`    页面上的「刷新」按钮将不可用。用 --py 指定正确路径。`);
  }
  if (!fs.existsSync(ROOT)) {
    console.warn(`[!] 根目录不存在，请先运行一次抓取生成 data/`);
  }
});

// 优雅退出（NSSM 停止服务时会发信号）
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`\n[i] 收到 ${sig}，正在关闭...`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 3000).unref();
  });
}
