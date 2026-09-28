# -*- coding: utf-8 -*-
"""用 DevTools 协议(CDP)对生产页做「真机渲染审计 + 截图」。

为什么不用 --screenshot CLI：
    Edge 153 起，`--screenshot` / `--dump-dom` 这类无头 CLI 参数会失效
    （rc=0、stderr 为空、文件不生成，极易误判成"页面有问题"）。
    但 --remote-debugging-port 仍然完好，所以改走 CDP。

前置：pip install websocket-client  （装在 envs/default）
用法：python tools/shoot_cdp.py
产物：preview/生产-桌面.png、preview/生产-窄屏.png、preview/审计-*.json
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TARGET = os.environ.get("SHOOT_TARGET") or (ROOT / "data" / "latest.html").resolve().as_uri()
TAG_SUFFIX = os.environ.get("SHOOT_SUFFIX", "")
OUT_DIR = ROOT / "preview"
TMP = ROOT / ".shot-tmp"
PORT = 9444

SHOTS = [
    # tag,      宽,   高(截取上限), 是否移动端
    ("桌面", 1440, 2600, False),
    ("窄屏", 500, 2800, True),
]

# 在页面里跑的布局审计：不只看"像不像"，而是量出来
AUDIT_JS = r"""
(function(){
  var o={};
  var de=document.documentElement;
  o.scrollW=de.scrollWidth;
  o.clientW=de.clientWidth;
  o.overflowX=de.scrollWidth-de.clientWidth;
  o.innerW=window.innerWidth;
  o.docH=de.scrollHeight;
  o.cards=document.querySelectorAll('.card').length;
  o.sections=document.querySelectorAll('section.section').length;
  o.revealTotal=document.querySelectorAll('.reveal').length;
  o.revealIn=document.querySelectorAll('.reveal.in').length;
  var c=document.querySelector('.card');
  o.cardOpacity=c?getComputedStyle(c).opacity:null;
  o.cardDisplay=c?getComputedStyle(c).display:null;
  var h1=document.querySelector('h1');
  o.h1=h1?h1.textContent.replace(/\s+/g,' ').trim():null;
  o.h1Height=h1?Math.round(h1.getBoundingClientRect().height):null;
  o.navOnDot=document.querySelectorAll('.nav-links a.on').length;
  o.refreshBtns=document.querySelectorAll('[data-refresh]').length;
  o.statsN=document.querySelectorAll('.stat').length;
  // 横向溢出时找出元凶元素
  if(o.overflowX>1){
    var worst=null,maxR=-1;
    Array.prototype.forEach.call(document.querySelectorAll('body *'),function(el){
      var r=el.getBoundingClientRect();
      if(r.right>maxR){
        maxR=r.right;
        worst=el.tagName.toLowerCase()+(el.className?('.'+String(el.className).trim().split(/\s+/).join('.')):'');
      }
    });
    o.worstRight=Math.round(maxR);
    o.worstEl=worst;
  }
  // 卡片实际像素宽度（确认栅格生效）
  var w=document.querySelector('.cards .card');
  o.cardW=w?Math.round(w.getBoundingClientRect().width):null;
  // 是否有元素文字被裁（clamp 生效的正常现象，只统计区块标题）
  return JSON.stringify(o);
})()
"""


class CDP:
    def __init__(self, url):
        from websocket import create_connection
        # suppress_origin：CDP 会拒绝带 Origin 头的握手（403），
        # 与其依赖 --remote-allow-origins，不如干脆不发这个头。
        try:
            self.ws = create_connection(url, timeout=60, suppress_origin=True,
                                        max_size=200 * 1024 * 1024)
        except TypeError:
            self.ws = create_connection(url, timeout=60,
                                        max_size=200 * 1024 * 1024)
        self._id = 0

    def send(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} -> {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True)
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_cdp(port, proc, seconds=20):
    """等调试端口就绪。进程若自己退了要立刻报出来，别干等。"""
    for _ in range(seconds * 2):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.load(r)
        except Exception:
            if proc.poll() is not None:
                return None
            time.sleep(0.5)
    return None


def page_ws(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
        for t in json.load(r):
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    return None


def main():
    if not Path(EDGE).exists():
        print(f"[x] 找不到 Edge: {EDGE}")
        return 1
    if not (ROOT / "data" / "latest.html").exists():
        print("[x] 缺 data/latest.html，先跑 build.py")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    udd = TMP / ("cdp-" + str(int(time.time())))
    udd.mkdir(parents=True, exist_ok=True)

    # 直接打开目标页：headless 开着 about:blank 有时会立刻自退，调试端口就没了
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--no-first-run", "--no-default-browser-check",
         f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
         "--remote-allow-origins=*",
         f"--user-data-dir={udd}", TARGET],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    ok = True
    try:
        ver = wait_cdp(PORT, proc)
        if not ver:
            print(f"[x] CDP 未就绪（进程 poll={proc.poll()}）")
            try:
                err = proc.stderr.read().decode("utf-8", "replace")
                if err.strip():
                    print("--- stderr ---")
                    print(err[-1200:])
            except Exception:
                pass
            return 1
        print(f"[i] 浏览器: {ver.get('Browser')}")

        cdp = CDP(page_ws(PORT))
        cdp.send("Page.enable")

        for tag, w, h, mobile in SHOTS:
            cdp.send("Emulation.setDeviceMetricsOverride",
                     width=w, height=1200, deviceScaleFactor=1, mobile=mobile)
            cdp.send("Page.navigate", url=TARGET)
            # 等真正加载完
            for _ in range(60):
                if cdp.js("document.readyState") == "complete":
                    break
                time.sleep(0.25)
            time.sleep(1.2)

            # ① 原始状态：验证 JS 是否真的跑起来了（reveal 应被逐步加上 .in）
            raw = json.loads(cdp.js(AUDIT_JS))
            # ② 模拟「动画已完成」的终态，再截全页（审布局而非审动画）
            cdp.js("document.querySelectorAll('.reveal').forEach(function(e){e.classList.add('in')});1")
            time.sleep(0.5)
            final = json.loads(cdp.js(AUDIT_JS))

            (OUT_DIR / f"审计-{tag}{TAG_SUFFIX}.json").write_text(
                json.dumps({"viewport": {"w": w, "h": h, "mobile": mobile},
                            "raw": raw, "final": final},
                           ensure_ascii=False, indent=2), encoding="utf-8")

            content_h = int(cdp.send("Page.getLayoutMetrics")["cssContentSize"]["height"])
            clip_h = min(content_h, h)
            shot = cdp.send("Page.captureScreenshot", format="png",
                            captureBeyondViewport=True,
                            clip={"x": 0, "y": 0, "width": w, "height": clip_h, "scale": 1})
            png = OUT_DIR / f"生产-{tag}{TAG_SUFFIX}.png"
            png.write_bytes(base64.b64decode(shot["data"]))

            flag = "OK " if png.stat().st_size > 5000 else "FAIL"
            print(f"[{flag}] {tag} {w}x{clip_h} -> {png.name} ({png.stat().st_size:,} B)")
            print(f"       卡片 {final['cards']} · 板块 {final['sections']} · "
                  f"横向溢出 {final['overflowX']}px · JS 原始已入场 {raw['revealIn']}/{raw['revealTotal']}")
            if final["overflowX"] > 1:
                ok = False
                print(f"       [!] 溢出元凶: {final.get('worstEl')} right={final.get('worstRight')}")
            if png.stat().st_size <= 5000:
                ok = False
        cdp.close()
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    print("\n结果:", "通过" if ok else "有问题")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
