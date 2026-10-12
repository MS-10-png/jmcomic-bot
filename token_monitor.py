#!/usr/bin/env python3
"""Token Monitor —— Ollama 实时 Token 监控（代理 + 桌面悬浮 Widget）

用法：
  1. 启动 Ollama（监听在 OLLAMA_BACKEND_PORT）
     # 例：%APPDATA%\Ollama\config.json {"listen_addr": "127.0.0.1","port":8889}
     ollama serve
  2. 运行本脚本：python token_monitor.py
  3. 将 Hermes 的模型 API 地址改为 127.0.0.1:11434（即本脚本地址）
  4. 桌面出现浮动窗口，浏览器打开 http://127.0.0.1:8877 可看完整面板
"""

import json
import time
import os
import threading
import http.client
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ═══════════════ 配置 ═══════════════
OLLAMA_BACKEND_HOST = "127.0.0.1"
OLLAMA_BACKEND_PORT = 8889     # Ollama 后端端口──必须手动改 Ollama 配置到不同端口
PROXY_PORT = 11434             # 代理端口──Hermes 指向这个──即 127.0.0.1
WEB_PORT = 8877                # Web 面板端口
# ══════════════════════════════════════


class TimeEntry:
    __slots__ = ("ts", "model", "t_in", "t_out", "ttfi_ms", "total_ms")

    def __init__(self, model, t_in, t_out, ttfi_ms, total_ms):
        self.ts = time.time()
        self.model = model
        self.t_in = t_in
        self.t_out = t_out
        self.ttfi_ms = ttfi_ms
        self.total_ms = total_ms


class TokenRecorder:
    """线程安全的 token 记录 + 聚合"""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = []

    def record(self, model, t_in, t_out, ttfi_ms, total_ms):
        with self._lock:
            self._entries.append(TimeEntry(model, t_in, t_out, ttfi_ms, total_ms))
            if len(self._entries) > 500:
                self._entries = self._entries[-500:]

    def _rec(self, n=60):
        cut = time.time() - n
        with self._lock:
            return [e for e in self._entries if e.ts >= cut]

    def _total(self):
        with self._lock:
            return sum(e.t_in for e in self._entries), sum(e.t_out for e in self._entries), len(self._entries)

    def snapshot(self):
        total_in, total_out, count = self._total()
        rec = self._rec()
        rate = sum(e.t_out for e in rec) / max(
            (rec[-1].ts + rec[-1].total_ms/1000) - rec[0].ts if len(rec) > 1 else 1, 0.01)
        avg_ttfi = sum(e.ttfi_ms for e in rec) / max(len(rec), 1)
        with self._lock:
            graph = [(i+1, e.ttfi_ms, e.t_out) for i, e in enumerate(self._entries[-100:] if len(self._entries[-100:]) > 1 else self._entries)]
        return json.dumps({
            "total_in": total_in, "total_out": total_out,
            "count": count, "rate": f"{rate:.1f}",
            "avg_ttfi": f"{avg_ttfi:.0f}", "graph": graph
        }).encode()


rec = TokenRecorder()

# 日志
_LOG = Path(__file__).parent / "logs" / "token_monitor.log"
_LOG.parent.mkdir(parents=True, exist_ok=True)

def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _error(self, code, msg):
        self.send_response(code); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps({"error":msg}).encode())

    def _forward(self, path, method="POST"):
        bl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(bl) if bl else None
        c = http.client.HTTPConnection(OLLAMA_BACKEND_HOST, OLLAMA_BACKEND_PORT, timeout=300)
        try:
            c.request(method, path, body=body, headers=dict(self.headers))
            r = c.getresponse(); data = r.read()
            self.send_response(r.status)
            for k,v in r.getheaders():
                if k.lower() not in ("transfer-encoding","content-length"): self.send_header(k,v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        finally:
            c.close()

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        models_api = ("/api/generate","/api/chat","/api/embed","/api/embeddings","/api/pull",
                      "/api/cancel","/api/show","/api/ps")
        if path not in models_api:
            self._forward(path, "POST"); return

        # ── 读请求体 ──
        bl = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(bl) if bl else b""
        try:
            req = json.loads(raw) if raw else {}
        except Exception:
            self._error(400, "bad json"); return
        model = req.get("model", "?")

        # ── 连后端 ──
        c = http.client.HTTPConnection(OLLAMA_BACKEND_HOST, OLLAMA_BACKEND_PORT, timeout=300)
        try:
            c.request("POST", self.path, body=raw, headers={"Content-Type":"application/json","Accept":"text/event-stream"}
                      if "Content-Type" in self.headers else None)
            # ponytail: use chunked transfer decoding from http.client (it handles this automatically)
            resp = c.getresponse()
        except Exception as exc:
            c.close(); self._error(502, f"Backend: {exc}"); return

        # ── 转发头 ──
        self.send_response(resp.status)
        for k,v in resp.getheaders():
            if k.lower() not in ("transfer-encoding","content-length"):
                self.send_header(k,v)
        self.end_headers()

        # ── 解析 SSE ── 每次只收一行 ──
        t0 = time.time(); first_tok = None
        total_in = 0; total_out = 0; final = {}
        # http.client 把响应体暴露为可迭代行（自动剥离 chunk 头尾）
        try:
            for chunk in resp:
                self.wfile.write(chunk); self.wfile.flush()
                text = chunk.decode("utf-8", errors="replace").strip()
                if not text: continue
                try:
                    d = json.loads(text)
                except json.JSONDecodeError:
                    continue
                pc = d.get("prompt_eval_count", 0)
                if pc: total_in += pc
                if first_tok is None and d.get("eval_count", 0):
                    first_tok = time.time()
                if d.get("done"):
                    total_out = d["eval_count"]
                    final = d
        except Exception as exc:
            _log(f"SSE parse err: {exc}")

        elapsed = (time.time()-t0)*1000
        ttfi = (first_tok-t0)*1000 if first_tok else 0
        # 兜底：用 done msg 的值
        if not total_out and final:
            total_out = final.get("eval_count", total_out)
        if not total_in and final:
            total_in = final.get("prompt_eval_count", total_in)

        rec.record(model, total_in, total_out, round(ttfi,1), round(elapsed,1))
        _log(f"{model:20s} in={total_in} out={total_out} ttfi={ttfi:.0f}ms t={elapsed:.0f}ms")

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p in ("/api/tags","/api/ping","/api/version","/api/show"):
            self._forward(p)
        else:
            self.send_error(404)


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p == "/":
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.end_headers(); self.wfile.write(WEB_HTML.encode()); return
        if p == "/api/stats":
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.end_headers(); self.wfile.write(rec.snapshot()); return
        self.send_error(404)


WEB_HTML = r"""<!DOCTYPE html>
<html lang=zh-CN><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',system-ui,sans-serif;padding:20px}
h1{color:#58a6ff;font-size:18px;margin-bottom:16px}
.g{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.c{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;text-align:center}
.c .l{font-size:12px;color:#8b949e;margin-bottom:6px}
.c .v{font-size:24px;font-weight:700}
.gw{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;height:220px}
#c{width:100%;height:100%;display:block}
.st{font-size:12px;color:#8b949e;margin-top:10px}
</style></head><body>
<h1>📊 Token Monitor — Ollama</h1>
<div class=g><div class=c><div class=l>输入 Token</div><div class=v id=vi>...</div></div>
<div class=c><div class=l>输出 Token</div><div class=v id=vo>...</div></div>
<div class=c><div class=l>产出速率</div><div class=v id=vr>...</div></div>
<div class=c><div class=l>最近请求</div><div class=v id=vc>...</div></div></div>
<div style=display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px>
<div class=c><div class=l>平均 TTFI</div><div class=v id=vt>...</div></div>
<div class=c><div class=l>模型</div><div class=v id=vm>离线</div></div></div>
<div class=gw><canvas id=c></canvas></div>
<div class=st id=st></div>
<script>const K=document.getElementById("c"),X=K.getContext("2d");let D=[];
async function T(){try{const s=await(await fetch("/api/stats",{signal:AbortSignal.timeout(2500)})).json();
document.getElementById("vi").textContent=s.total_in.toLocaleString();
document.getElementById("vo").textContent=s.total_out.toLocaleString();
document.getElementById("vr").innerHTML=`${s.rate}<span style="color:#8b949e">tok/s</span>`;
document.getElementById("vc").textContent=s.count;
document.getElementById("vt").innerHTML=`${s.avg_ttfi}<span style="color:#8b949e">ms</span>`;
D=s.graph.map(g=>({y:g[2],z:g[1]}));
const W=K.width=K.clientWidth*devicePixelRatio,H=K.height=K.clientHeight*devicePixelRatio;
X.clearRect(0,0,W,H);X.strokeStyle="#21262d";X.lineWidth=1;
[0,1,2,3,4].forEach(i=>{const y=H*.08+i*H*.18;X.beginPath();X.moveTo(0,y);X.lineTo(W,y);X.stroke()});
if(!D.length)return;const m=Math.max(...D.map(d=>d.y),1)||1;
X.strokeStyle="#3fb950";X.lineWidth=2;X.beginPath();
D.forEach((d,i)=>{const x=i/(D.length-1)*W,y=H-(d.y/m)*H*.75-H*.05;i?X.lineTo(x,y):X.moveTo(x,y)});X.stroke();
document.getElementById("st").textContent=new Date().toLocaleTimeString()
}catch(e){document.getElementById("st").textContent="❌ "+e.message}}
T();setInterval(T,1500)
</script></body></html>"""


# ═══════════════ 桌面悬浮窗口 ═══════════════
def _float_widget():
    """桌面浮动 widget──透明、置顶、可拖拽、不抢焦点"""
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk(className="TokenWidget")          # 不进入任务栏
    root.configure(bg="transparent")
    root.overrideredirect(True)
    root.attributes("-transparentcolor", "transparent")
    root.attributes("-topmost", True)

    # 大小 + 位置（屏幕右上角）
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    W, H = 280, 140
    root.geometry(f"{W}x{H}+{sw-W-10}+20")

    F = tkfont.Font(family="Segoe UI", size=11)
    B = "#1c2028"   # 卡片底色
    T = "#c9d1d9"
    ACC = "#58a6ff"

    # ── 主面板（圆角模拟 + 半透明深色） ──
    panel = tk.Frame(root, bg=B, bd=1, relief="flat")
    panel.pack(expand=True, fill="both", padx=8, pady=8)
    panel.pack_propagate(False)

    def hex2rgba(h, a=0.0):
        """RGBA 合成到 Tkinter"""
        return root.winfo_rgb(h) + (a,)

    # ── 标题 ──
    tk.Label(panel, text="⚡ Token Monitor", font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
             bg=B, fg=ACC, bd=0).pack(pady=(6, 0))

    # ── 统计行 ──
    vals = [tk.IntVar(), tk.IntVar(), tk.DoubleVar(), tk.DoubleVar(), tk.StringVar()]

    def _row(label, var, bold=False, accent=None, pad=2):
        f = tkfont.Font(family="Consolas" if bold else "Segoe UI", size=10)
        tk.Label(panel, text=label, bg=B, fg=accent or "#8b949e", font=f, bd=0, pady=pad).pack(fill="x", padx=10)
        if isinstance(var, tk.IntVar):
            tk.Label(panel, textvariable=var, bg=B, fg=T, font=tkfont.Font(family="Consolas", size=14, weight="bold"),
                     bd=0, pady=0).pack(fill="x", padx=10)
        elif isinstance(var, tk.DoubleVar):
            tk.Label(panel, textvariable=var, bg=B, fg=accent or "#f0f6fc",
                     font=tkfont.Font(family="Consolas", size=14, weight="bold"), bd=0, pady=0).pack(fill="x", padx=10)
        elif isinstance(var, tk.StringVar):
            tk.Label(panel, textvariable=var, bg=B, fg=T, bd=0, pady=0).pack(fill="x", padx=10)

    _row("  输入 Token:      ", vals[0])
    _row("  输出 Token:      ", vals[1])
    _row("  产出速率:       ", vals[2])
    tk.Label(panel, text="  平均 TTFI:       ", bg=B, fg="#8b949e",
             font=tkfont.Font(family="Consolas", size=11), bd=0).pack(fill="x", padx=10)
    tk.Label(panel, textvariable=vals[3], bg=B, fg="#f0883e",
             font=tkfont.Font(family="Consolas", size=14, weight="bold"), bd=0).pack(fill="x", padx=10)
    _row("  状态:           ", vals[4])

    # ── 拖拽 ──
    root.bind("<ButtonPress-1>", lambda e: (root._drag_x,e.x,root._drag_y,e.y))
    root.bind("<B1-Motion>",      lambda e: (root.wm_geometry(f"+{root.winfo_x()+e.x-root._drag_x}+{root.winfo_y()+e.y-root._drag_y}"),
                                               None))

    # ── 轮询更新 ──
    def _upd():
        try:
            c = http.client.HTTPConnection("127.0.0.1", WEB_PORT, timeout=2)
            c.request("GET", "/api/stats"); s = json.loads(c.getresponse().read())
            vals[0].set(f"{s['total_in']:,}"); vals[1].set(f"{s['total_out']:,}")
            vals[2].set(f"{s['rate']} tok/s"); vals[3].set(f"{s['avg_ttfi']} ms")
            vals[4].set(f"✓  {len(s['graph'])} 条记录  {time.strftime('%H:%M:%S')}")
        except:
            vals[4].set("✗  断连")
        root.after(2000, _upd)
    _upd()
    root.mainloop()


# ═══════════════ 入口 ═══════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════╗")
    print("║   Token Monitor — Ollama 实时面板    ║")
    print("╚══════════════════════════════════════╝")
    print(f"  Ollama 后端: {OLLAMA_BACKEND_HOST}:{OLLAMA_BACKEND_PORT}  (需手动改 Ollama 配置)")
    print(f"  代理:        127.0.0.1:{PROXY_PORT}          (Hermes 指向此端口)")
    print(f"  Web 面板:    http://localhost:{WEB_PORT}")
    print(f"  桌面 Widget: 自动启动（顶部浮动条）")
    print(f"  日志: {_LOG}")
    print(f"\n⚠  Ollama 必须已在此端口启动：{OLLAMA_BACKEND_HOST}:{OLLAMA_BACKEND_PORT}")

    # 检查后端端口
    test = http.client.HTTPConnection(OLLAMA_BACKEND_HOST, OLLAMA_BACKEND_PORT, timeout=2)
    try:
        test.request("GET", "/api/ping")
        r = test.getresponse(); r.read()
        if r.status == 200:
            print("  ✅ Ollama 后端连接正常")
    except:
        print("  ⚠  Ollama 后端无响应——请确认 Ollama 已在本机" + str(OLLAMA_BACKEND_PORT) + " 端口启动")
    finally:
        test.close()

    proxy = HTTPServer(("127.0.0.1", PROXY_PORT), ProxyHandler)
    web   = HTTPServer(("127.0.0.1", WEB_PORT), WebHandler)

    t1 = threading.Thread(target=proxy.serve_forever, daemon=True)
    t2 = threading.Thread(target=web.serve_forever, daemon=True)
    t1.start(); t2.start()

    print("  ▶ 已启动，按 Ctrl+C 停止")

    # 桌面 widget
    try:
        _float_widget()
    except Exception as exc:
        print(f"  ⚠  桌面窗口启动失败: {exc}（功能不受影响）")

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n  已停止")
        proxy.shutdown(); web.shutdown()

