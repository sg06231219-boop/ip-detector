from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx
import os
import json
import io
import csv
import time
import asyncio
import base64
from datetime import datetime
from typing import Optional, Dict, Any

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ========== 配置 ==========
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Lys13579")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = "sg06231219-boop/ip-detector"
GITHUB_BRANCH = "data"
VISITS_PATH = "data/visits.json"
# Save throttle: batch changes before pushing to GitHub
_pending_saves = 0
_SAVE_THRESHOLD = 5
_last_save_time = 0.0
_SAVE_INTERVAL = 120

# ========== IP位置缓存（内存，1小时TTL） ==========
_location_cache: Dict[str, Any] = {}
_location_cache_ttl: Dict[str, float] = {}
LOCATION_CACHE_TTL = 3600  # 1小时

# ========== 数据存储（GitHub Contents API 持久化） ==========
def _github_get_visits() -> list:
    """Read visits.json from GitHub (3 retries)"""
    for attempt in range(3):
        try:
            headers = {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_PATH}?ref={GITHUB_BRANCH}"
            resp = httpx.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                decoded = base64.b64decode(data["content"]).decode("utf-8")
                visits = json.loads(decoded)
                return visits if isinstance(visits, list) else []
            if resp.status_code == 404: return []
        except Exception:
            if attempt < 2: import time as _t; _t.sleep(1)
    return []

def _github_save_visits(visits: list) -> bool:
    """Save visits.json to GitHub (3 retries)"""
    for attempt in range(3):
        try:
            headers = {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_PATH}?ref={GITHUB_BRANCH}"
            resp = httpx.get(url, headers=headers, timeout=15)
            sha = resp.json().get("sha") if resp.status_code == 200 else None
            encoded = base64.b64encode(json.dumps(visits, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8")
            body = {"message": f"Update visits ({len(visits)})", "content": encoded, "branch": GITHUB_BRANCH}
            if sha: body["sha"] = sha
            resp = httpx.put(url, headers=headers, json=body, timeout=20)
            if resp.status_code in (200, 201): return True
            if resp.status_code == 409: continue
        except Exception:
            if attempt < 2: import time as _t; _t.sleep(1)
    return False

# 内存缓存（避免每次请求都读GitHub）
_visits_cache: list = []
_visits_cache_time: float = 0
_VISITS_CACHE_TTL = 30  # 30秒缓存

def _load_visits() -> list:
    global _visits_cache, _visits_cache_time
    now = time.time()
    if now - _visits_cache_time < _VISITS_CACHE_TTL:
        return _visits_cache
    visits = _github_get_visits()
    _visits_cache = visits
    _visits_cache_time = now
    return visits

def _save_visits(visits: list, force: bool = False):
    global _visits_cache, _visits_cache_time, _pending_saves, _last_save_time
    if len(visits) > 2000:
        visits = visits[-2000:]
    _visits_cache = visits
    _visits_cache_time = time.time()
    _pending_saves += 1
    now = time.time()
    should_push = force or _pending_saves >= _SAVE_THRESHOLD or (now - _last_save_time) >= _SAVE_INTERVAL
    if should_push:
        _pending_saves = 0
        _last_save_time = now
        _github_save_visits(visits)

def _record_visit(ip: str, location: dict, user_agent: str = "", referer: str = ""):
    """记录访问，同IP 5分钟内去重"""
    visits = _load_visits()
    now = datetime.now()
    for v in reversed(visits[-50:]):  # 只检查最近50条
        if v.get("ip") == ip:
            try:
                last_time = datetime.strptime(v["time"], "%Y-%m-%d %H:%M:%S")
                if (now - last_time).total_seconds() < 300:
                    return v
            except Exception:
                pass
    visit = {
        "ip": ip,
        "country": location.get("country", "未知"),
        "country_code": location.get("country_code", ""),
        "city": location.get("city", "未知"),
        "region": location.get("region_name", "未知"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "timezone": location.get("timezone", "未知"),
        "isp": location.get("isp", "未知"),
        "as": location.get("as", "未知"),
        "user_agent": user_agent[:200] if user_agent else "",
        "referer": referer[:200] if referer else "",
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    visits.append(visit)
    _save_visits(visits)
    return visit

def _delete_visit(index: int):
    """删除指定索引的访问记录"""
    visits = _load_visits()
    if 0 <= index < len(visits):
        visits.pop(index)
        _save_visits(visits)
        return True
    return False

def _get_client_ip(request: Request) -> str:
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        return ip.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

async def _fetch_location(ip: str) -> dict:
    """查询IP地理位置（带内存缓存）"""
    now = time.time()
    cache_key = f"loc_{ip}"
    if cache_key in _location_cache:
        if now - _location_cache_ttl.get(cache_key, 0) < LOCATION_CACHE_TTL:
            return _location_cache[cache_key]
    try:
        async with httpx.AsyncClient() as client:
            fields = "status,message,country,countryCode,city,lat,lon,timezone,isp,as,regionName,zip"
            resp = await client.get(
                f"http://ip-api.com/json/{ip}?lang=zh-CN&fields={fields}",
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    result = {
                        "country": data.get("country", "未知"),
                        "country_code": data.get("countryCode", "未知"),
                        "city": data.get("city", "未知"),
                        "latitude": data.get("lat", "未知"),
                        "longitude": data.get("lon", "未知"),
                        "timezone": data.get("timezone", "未知"),
                        "isp": data.get("isp", "未知"),
                        "as": data.get("as", "未知"),
                        "region_name": data.get("regionName", "未知"),
                        "zip": data.get("zip", "未知"),
                    }
                    _location_cache[cache_key] = result
                    _location_cache_ttl[cache_key] = now
                    return result
    except Exception:
        pass
    return {}

def get_country_flag(code: str) -> str:
    if not code or len(code) != 2:
        return "🏁"
    try:
        offset = 127397
        return chr(ord(code[0].upper()) + offset) + chr(ord(code[1].upper()) + offset)
    except Exception:
        return "🏁"


# ========== 前台页面模板 ==========
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IP位置检测 - 智能定位工具</title>
    <meta name="description" content="一键检测您的IP地址、地理位置、ISP信息。免费、快速、精准的IP定位工具。">
    <meta name="keywords" content="IP定位,IP查询,IP地址查询,地理位置,IP检测">
    <meta property="og:title" content="IP位置检测 - 智能定位工具">
    <meta property="og:description" content="一键检测您的IP地址、地理位置、ISP信息，免费使用">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://ip-detector-lu2p.onrender.com">
    <meta name="twitter:card" content="summary">
    <meta name="theme-color" content="#0a0e27">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌍</text></svg>">
    <style>
        :root {
            --bg-primary: #0a0e27;
            --bg-secondary: #111640;
            --bg-card: rgba(255,255,255,0.04);
            --bg-card-hover: rgba(255,255,255,0.08);
            --text-primary: #e8eaf6;
            --text-secondary: #9fa8da;
            --text-muted: #5c6bc0;
            --accent: #7c4dff;
            --accent2: #448aff;
            --accent3: #18ffff;
            --border: rgba(124,77,255,0.2);
            --success: #69f0ae;
            --danger: #ff5252;
        }
        [data-theme="light"] {
            --bg-primary: #f0f4ff;
            --bg-secondary: #ffffff;
            --bg-card: rgba(0,0,0,0.03);
            --bg-card-hover: rgba(124,77,255,0.06);
            --text-primary: #1a1a2e;
            --text-secondary: #4a4a6a;
            --text-muted: #8888aa;
            --border: rgba(124,77,255,0.15);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary); color: var(--text-primary);
            min-height: 100vh; overflow-x: hidden;
            transition: background 0.3s, color 0.3s;
        }
        [data-theme="light"] body { background: var(--bg-primary); }
        #particles {
            position: fixed; top:0; left:0; width:100%; height:100%;
            z-index: 0; pointer-events: none;
        }
        .wrapper {
            position: relative; z-index: 1;
            max-width: 900px; margin: 0 auto; padding: 30px 20px;
        }
        .topbar {
            display: flex; justify-content: flex-end; gap: 8px;
            margin-bottom: 10px;
        }
        .topbar button {
            background: var(--bg-card); border: 1px solid var(--border);
            color: var(--text-secondary); padding: 6px 12px;
            border-radius: 8px; cursor: pointer; font-size: 13px;
            display: flex; align-items: center; gap: 4px;
            transition: all 0.2s;
        }
        .topbar button:hover { border-color: var(--accent); color: var(--accent); }
        .header {
            text-align: center; padding: 40px 0 30px;
            animation: fadeInDown 0.6s ease-out;
        }
        .header h1 {
            font-size: clamp(32px, 7vw, 48px); font-weight: 800;
            background: linear-gradient(135deg, var(--accent), var(--accent2), var(--accent3));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text; margin-bottom: 8px;
        }
        .header p { color: var(--text-secondary); font-size: 15px; }
        .social-proof {
            margin-top: 10px; font-size: 12px; color: var(--text-muted);
        }
        .social-proof span { color: var(--accent3); font-weight: 700; }
        .status-badge {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(105,240,174,0.1); border: 1px solid rgba(105,240,174,0.3);
            padding: 4px 14px; border-radius: 20px; font-size: 12px;
            color: var(--success); margin-top: 12px;
        }
        .status-dot {
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--success); animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%,100% { opacity:1; transform:scale(1); }
            50% { opacity:0.5; transform:scale(1.5); }
        }
        .query-section { margin: 20px 0; animation: fadeInUp 0.6s ease-out 0.15s both; }
        .query-box { display: flex; gap: 10px; max-width: 600px; margin: 0 auto; }
        .query-box input {
            flex: 1; padding: 14px 18px; border-radius: 14px;
            border: 1px solid var(--border); background: var(--bg-card);
            color: var(--text-primary); font-size: 15px; outline: none;
            font-family: 'Courier New', monospace; transition: border-color 0.3s;
        }
        .query-box input:focus { border-color: var(--accent); }
        .query-box input::placeholder { color: var(--text-muted); font-family: sans-serif; }
        .query-box button {
            padding: 14px 24px; border-radius: 14px; border: none;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: white; font-size: 14px; font-weight: 600; cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s; white-space: nowrap;
        }
        .query-box button:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,77,255,0.3); }
        .query-box button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .query-result { margin: 20px 0; animation: fadeInUp 0.5s ease-out; }
        .query-result .ip-hero { text-align: center; margin: 20px 0; }
        .query-result .ip-label { color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 8px; }
        .query-result .ip-value {
            font-size: clamp(28px, 6vw, 48px); font-weight: 800;
            font-family: 'Courier New', monospace;
            background: linear-gradient(90deg, var(--accent3), var(--accent2));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
            cursor: pointer; transition: filter 0.2s;
        }
        .query-result .ip-value:hover { filter: brightness(1.3); }
        .ip-hero {
            text-align: center; margin: 30px 0;
            animation: fadeInUp 0.6s ease-out 0.2s both;
        }
        .ip-hero .ip-label { color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 8px; }
        .ip-hero .ip-value {
            font-size: clamp(28px, 6vw, 48px); font-weight: 800;
            font-family: 'Courier New', monospace;
            background: linear-gradient(90deg, var(--accent3), var(--accent2));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
            cursor: pointer; position: relative; transition: filter 0.2s;
        }
        .ip-hero .ip-value:hover { filter: brightness(1.3); }
        .ip-hero .copy-hint { font-size: 11px; color: var(--text-muted); margin-top: 6px; opacity: 0.6; transition: opacity 0.3s; }
        .ip-hero .ip-value:hover + .copy-hint { opacity: 1; }
        .info-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px; margin: 30px 0;
        }
        .info-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 16px; padding: 20px; backdrop-filter: blur(10px);
            transition: all 0.3s ease; animation: fadeInUp 0.5s ease-out both;
        }
        .info-card:hover {
            background: var(--bg-card-hover); border-color: rgba(124,77,255,0.4);
            transform: translateY(-2px); box-shadow: 0 8px 32px rgba(124,77,255,0.15);
        }
        .info-card .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        .info-card .card-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
        .info-card .card-title { font-size: 13px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }
        .info-card .card-value { font-size: 20px; font-weight: 700; color: var(--text-primary); word-break: break-all; }
        .info-card .card-sub { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
        .card-location .card-icon { background: rgba(124,77,255,0.15); }
        .card-city .card-icon { background: rgba(68,138,255,0.15); }
        .card-coords .card-icon { background: rgba(24,255,255,0.15); }
        .card-timezone .card-icon { background: rgba(255,214,0,0.15); }
        .card-isp .card-icon { background: rgba(105,240,174,0.15); }
        .card-as .card-icon { background: rgba(255,145,0,0.15); }
        .card-region .card-icon { background: rgba(255,82,82,0.15); }
        .card-browser .card-icon { background: rgba(234,128,252,0.15); }
        .map-section { margin: 30px 0; animation: fadeInUp 0.6s ease-out 0.8s both; }
        .map-section h3 { font-size: 16px; color: var(--text-secondary); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
        .map-container { border-radius: 16px; overflow: hidden; border: 1px solid var(--border); height: 300px; background: var(--bg-secondary); }
        .map-container iframe { width: 100%; height: 100%; border: none; }
        [data-theme="dark"] .map-container iframe { filter: invert(0.9) hue-rotate(180deg) brightness(0.9) contrast(1.1); }
        .actions { display: flex; gap: 12px; flex-wrap: wrap; margin: 24px 0; animation: fadeInUp 0.6s ease-out 1s both; }
        .btn {
            flex: 1; min-width: 140px; padding: 14px 20px; border-radius: 12px; border: none;
            cursor: pointer; font-size: 14px; font-weight: 600;
            display: flex; align-items: center; justify-content: center; gap: 8px; transition: all 0.3s; text-decoration: none;
        }
        .btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: white; }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,77,255,0.3); }
        .btn-secondary { background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); }
        .btn-secondary:hover { background: var(--bg-card-hover); border-color: var(--accent); }
        .btn-success { background: rgba(105,240,174,0.15); color: var(--success); border: 1px solid rgba(105,240,174,0.3); }
        .btn-success:hover { background: rgba(105,240,174,0.25); }
        .toast {
            position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(100px);
            background: var(--bg-secondary); border: 1px solid var(--accent);
            color: var(--text-primary); padding: 12px 24px; border-radius: 12px;
            font-size: 14px; z-index: 1000; transition: transform 0.3s ease; pointer-events: none;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        .toast.show { transform: translateX(-50%) translateY(0); }
        .json-section { margin: 30px 0; animation: fadeInUp 0.6s ease-out 1.2s both; }
        .json-toggle {
            background: none; border: none; color: var(--text-muted);
            font-size: 13px; cursor: pointer; padding: 8px 0;
            display: flex; align-items: center; gap: 6px;
        }
        .json-toggle:hover { color: var(--text-secondary); }
        .json-toggle .arrow { transition: transform 0.3s; display: inline-block; }
        .json-toggle.open .arrow { transform: rotate(90deg); }
        .json-content {
            background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
            padding: 16px; margin-top: 8px; font-family: 'Courier New', monospace; font-size: 12px;
            color: var(--accent3); overflow-x: auto; max-height: 0; overflow: hidden;
            transition: max-height 0.3s ease, padding 0.3s; padding: 0 16px;
        }
        .json-content.show { max-height: 600px; padding: 16px; }
        .footer { text-align: center; padding: 30px 0 20px; color: var(--text-muted); font-size: 12px; border-top: 1px solid var(--border); margin-top: 40px; }
        .footer a { color: var(--accent2); text-decoration: none; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeInUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeInDown { from { opacity:0; transform:translateY(-20px); } to { opacity:1; transform:translateY(0); } }
        .info-card:nth-child(1) { animation-delay: 0.3s; }
        .info-card:nth-child(2) { animation-delay: 0.4s; }
        .info-card:nth-child(3) { animation-delay: 0.5s; }
        .info-card:nth-child(4) { animation-delay: 0.6s; }
        .info-card:nth-child(5) { animation-delay: 0.7s; }
        .info-card:nth-child(6) { animation-delay: 0.8s; }
        .info-card:nth-child(7) { animation-delay: 0.9s; }
        .info-card:nth-child(8) { animation-delay: 1.0s; }
        @media (max-width: 600px) {
            .wrapper { padding: 16px 12px; }
            .header h1 { font-size: 28px; }
            .ip-hero .ip-value { font-size: 28px; }
            .info-grid { grid-template-columns: 1fr; gap: 12px; }
            .map-container { height: 220px; }
            .actions { flex-direction: column; }
            .query-box { flex-direction: column; }
            .query-box button { width: 100%; }
        }
    
    .live-visitors{margin-top:16px;display:flex;justify-content:center;gap:12px;flex-wrap:wrap}
    .live-visitors-section{margin:20px 0;animation:fadeInUp .6s ease-out .25s both}
    .lv-header{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;color:var(--text-secondary);margin-bottom:12px}
    .lv-dot{width:8px;height:8px;border-radius:50%;background:var(--success);animation:pulse 2s infinite}
    .lv-list{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;scrollbar-width:thin}
    .lv-card{background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:12px 16px;min-width:180px;flex-shrink:0;transition:all .3s;cursor:default}
    .lv-card:hover{border-color:rgba(124,77,255,.4);transform:translateY(-2px);box-shadow:0 8px 24px rgba(124,77,255,.15)}
    .lv-card-top{display:flex;align-items:center;gap:8px;margin-bottom:6px}
    .lv-card .lv-flag{font-size:22px}
    .lv-card .lv-ip{color:var(--accent3);font-family:'Courier New',monospace;font-weight:700;font-size:13px}
    .lv-card .lv-loc{color:var(--text-secondary);font-size:12px}
    .lv-card .lv-time{color:var(--text-muted);font-size:11px;margin-top:4px}
    .lv-card .lv-live{width:6px;height:6px;border-radius:50%;background:var(--success);animation:pulse 2s infinite;margin-left:auto}
</style>
</head>
<body>
    <canvas id="particles"></canvas>
    <div class="wrapper">
        <div class="topbar">
            <button onclick="toggleTheme()" id="themeBtn">🌙</button>
            <button onclick="sharePage()">🔗 分享</button>
        </div>
        <div class="header">
            <h1>🌍 IP 智能定位</h1>
            <p>实时检测您的网络身份与地理位置</p>
            <div class="social-proof">已有 <span id="totalUsers">-</span> 人使用</div>
            <div class="status-badge">
                <span class="status-dot"></span>
                检测完成 · __TIMESTAMP__
            </div>
        </div>
        <div id="liveVisitors" class="live-visitors-section">
            <div class="lv-header"><span class="lv-dot"></span> 实时访客动态</div>
            <div id="lvList" class="lv-list"></div>
        </div>
        <div class="query-section">
            <div class="query-box">
                <input type="text" id="queryInput" placeholder="输入任意IP地址查询位置，例如：8.8.8.8" onkeydown="if(event.key==='Enter')queryIP()">
                <button onclick="queryIP()" id="queryBtn">🔍 查询IP</button>
            </div>
            <div id="queryResult"></div>
        </div>
        <div class="ip-hero">
            <div class="ip-label">您的公网 IP 地址</div>
            <div class="ip-value" onclick="copyIP()" title="点击复制">__IP__</div>
            <div class="copy-hint">点击IP即可复制</div>
        </div>
        <div class="info-grid" id="infoGrid">
            <div class="info-card card-location">
                <div class="card-header"><div class="card-icon">🏳️</div><div class="card-title">国家/地区</div></div>
                <div class="card-value">__COUNTRY_FLAG__ __COUNTRY__</div>
                <div class="card-sub">代码: __COUNTRY_CODE__</div>
            </div>
            <div class="info-card card-city">
                <div class="card-header"><div class="card-icon">🏙️</div><div class="card-title">城市</div></div>
                <div class="card-value">__CITY__</div>
                <div class="card-sub">地区: __REGION__</div>
            </div>
            <div class="info-card card-coords">
                <div class="card-header"><div class="card-icon">🗺️</div><div class="card-title">经纬度</div></div>
                <div class="card-value">__LAT__, __LON__</div>
                <div class="card-sub">WGS84坐标系</div>
            </div>
            <div class="info-card card-timezone">
                <div class="card-header"><div class="card-icon">⏰</div><div class="card-title">时区</div></div>
                <div class="card-value">__TIMEZONE__</div>
                <div class="card-sub" id="localTime">本地时间: 加载中...</div>
            </div>
            <div class="info-card card-isp">
                <div class="card-header"><div class="card-icon">🌐</div><div class="card-title">ISP 运营商</div></div>
                <div class="card-value">__ISP__</div>
                <div class="card-sub">互联网服务提供商</div>
            </div>
            <div class="info-card card-as">
                <div class="card-header"><div class="card-icon">🔗</div><div class="card-title">AS 编号</div></div>
                <div class="card-value" style="font-size:16px;">__AS__</div>
                <div class="card-sub">自治系统编号</div>
            </div>
            <div class="info-card card-region">
                <div class="card-header"><div class="card-icon">📍</div><div class="card-title">精确区域</div></div>
                <div class="card-value" style="font-size:16px;">__REGION_NAME__</div>
                <div class="card-sub">邮编: __ZIP__</div>
            </div>
            <div class="info-card card-browser">
                <div class="card-header"><div class="card-icon">🖥️</div><div class="card-title">您的浏览器</div></div>
                <div class="card-value" style="font-size:14px;" id="browserInfo">检测中...</div>
                <div class="card-sub" id="screenInfo"></div>
            </div>
        </div>
        <div class="map-section">
            <h3>📍 地理位置可视化</h3>
            <div class="map-container">
                <iframe id="mapFrame" src="https://www.openstreetmap.org/export/embed.html?bbox=__MAP_BBOX__&layer=mapnik&marker=__LAT__,__LON__" loading="lazy"></iframe>
            </div>
        </div>
        <div class="actions">
            <a href="https://www.google.com/maps?q=__LAT__,__LON__" target="_blank" class="btn btn-primary">🗺️ Google地图查看</a>
            <button class="btn btn-secondary" onclick="copyAll()">📋 复制全部信息</button>
            <button class="btn btn-success" onclick="copyIP()">📌 复制IP地址</button>
        </div>
        <div class="json-section">
            <button class="json-toggle" onclick="toggleJSON(this)">
                <span class="arrow">▶</span> 查看 JSON 原始数据
            </button>
            <div class="json-content" id="jsonContent">__JSON_DATA__</div>
        </div>
        <div class="footer">
            IP智能定位工具 · 数据来源 ip-api.com · 检测时间 __TIMESTAMP__<br>
            <span style="opacity:0.5;">位置为大致估算，不代表精确住址</span><br>
            <a href="/admin" style="color:var(--text-muted);font-size:11px;margin-top:4px;display:inline-block">🔒 管理后台</a>
        </div>
    </div>
    <div class="toast" id="toast"></div>
    <script>
    (function(){
        var saved = localStorage.getItem('ip-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        document.getElementById('themeBtn').textContent = saved === 'dark' ? '☀️' : '🌙';
    })();
    function toggleTheme() {
        var cur = document.documentElement.getAttribute('data-theme') || 'dark';
        var next = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('ip-theme', next);
        document.getElementById('themeBtn').textContent = next === 'dark' ? '☀️' : '🌙';
    }
    function sharePage() {
        var url = location.href;
        if (navigator.share) {
            navigator.share({ title: 'IP智能定位', text: '我的IP: __IP__', url: url }).catch(function(){});
        } else {
            navigator.clipboard.writeText(url).then(function(){ showToast('✅ 链接已复制'); });
        }
    }
    // 社会证明 - 加载使用人数
    fetch('/api/stats').then(function(r){return r.json()}).then(function(d){
        document.getElementById('totalUsers').textContent = d.total || 0;
    }).catch(function(){});

    var queryCache = {};
    function queryIP() {
        var input = document.getElementById('queryInput');
        var btn = document.getElementById('queryBtn');
        var ip = input.value.trim();
        if (!ip) { showToast('⚠️ 请输入IP地址'); return; }
        var ipRe = /^(\d{1,3}\.){3}\d{1,3}$/;
        if (!ipRe.test(ip)) { showToast('⚠️ IP格式不正确'); return; }
        btn.disabled = true; btn.textContent = '查询中...';
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        fetch('/api/query?ip=' + encodeURIComponent(ip))
            .then(function(r){ return r.json(); })
            .then(function(d){
                btn.disabled = false; btn.textContent = '🔍 查询IP';
                if (d.error) { showToast('❌ ' + d.error); return; }
                var l = d.location || {};
                var flag = codeToFlag(l.country_code || '');
                var lat = l.latitude || 0, lon = l.longitude || 0;
                var mapBBox = '';
                if (lat && lon) { var d2 = 0.05; mapBBox = (lon-d2) + ',' + (lat-d2) + ',' + (lon+d2) + ',' + (lat+d2); }
                var mapUrl = 'https://www.openstreetmap.org/export/embed.html?bbox=' + mapBBox + '&layer=mapnik&marker=' + lat + ',' + lon;
                var mapFilter = isDark ? 'invert(0.9) hue-rotate(180deg) brightness(0.9) contrast(1.1)' : 'none';
                var html = '<div class="query-result" style="margin-top:20px">' +
                    '<div class="ip-hero" style="margin:16px 0 20px">' +
                    '<div class="ip-label">查询结果</div>' +
                    '<div class="ip-value" onclick="navigator.clipboard.writeText(\\''+ip+'\\').then(function(){showToast(\\'✅ IP已复制\\')})">' + ip + '</div>' +
                    '</div>' +
                    '<div class="info-grid">' +
                    cardHTML('🏳️','国家/地区', flag + ' ' + (l.country||'未知'), '代码: ' + (l.country_code||'-')) +
                    cardHTML('🏙️','城市', (l.city||'未知'), '地区: ' + (l.region_name||'未知')) +
                    cardHTML('🗺️','经纬度', lat + ', ' + lon, 'WGS84坐标系') +
                    cardHTML('⏰','时区', (l.timezone||'未知'), '') +
                    cardHTML('🌐','ISP', (l.isp||'未知'), '') +
                    cardHTML('🔗','AS编号', (l.as||'-'), '') +
                    cardHTML('📍','邮编', (l.zip||'-'), '') +
                    '</div>' +
                    '<div class="map-section"><h3>📍 位置可视化</h3>' +
                    '<div class="map-container"><iframe src="'+mapUrl+'" style="width:100%;height:100%;border:none;filter:'+mapFilter+'" loading="lazy"></iframe></div></div>' +
                    '<div class="actions">' +
                    '<a href="https://www.google.com/maps?q='+lat+','+lon+'" target="_blank" class="btn btn-primary">🗺️ Google地图</a>' +
                    '<button class="btn btn-success" onclick="navigator.clipboard.writeText(\\''+ip+'\\').then(function(){showToast(\\'✅ IP已复制\\')})">📌 复制IP</button>' +
                    '</div></div>';
                document.getElementById('queryResult').innerHTML = html;
            })
            .catch(function(err){ btn.disabled=false; btn.textContent='🔍 查询IP'; showToast('❌ 查询失败'); });
    }
    function cardHTML(icon, title, value, sub) {
        return '<div class="info-card"><div class="card-header"><div class="card-icon">'+icon+'</div><div class="card-title">'+title+'</div></div><div class="card-value">'+value+'</div>'+(sub?'<div class="card-sub">'+sub+'</div>':'')+'</div>';
    }
    (function(){
        var c=document.getElementById('particles'),ctx=c.getContext('2d'),ps=[];
        function resize(){c.width=window.innerWidth;c.height=window.innerHeight} resize();
        window.addEventListener('resize',resize);
        for(var i=0;i<60;i++)ps.push({x:Math.random()*c.width,y:Math.random()*c.height,vx:(Math.random()-0.5)*0.3,vy:(Math.random()-0.5)*0.3,r:Math.random()*1.5+0.5,o:Math.random()*0.4+0.1});
        function draw(){ctx.clearRect(0,0,c.width,c.height);for(var i=0;i<ps.length;i++){var p=ps[i];p.x+=p.vx;p.y+=p.vy;if(p.x<0)p.x=c.width;if(p.x>c.width)p.x=0;if(p.y<0)p.y=c.height;if(p.y>c.height)p.y=0;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fillStyle='rgba(124,77,255,'+p.o+')';ctx.fill();for(var j=i+1;j<ps.length;j++){var q=ps[j],dx=p.x-q.x,dy=p.y-q.y,d2=Math.sqrt(dx*dx+dy*dy);if(d2<120){ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.strokeStyle='rgba(124,77,255,'+(0.08*(1-d2/120))+')';ctx.stroke()}}}requestAnimationFrame(draw)}draw();
    })();
    (function(){
        var ua=navigator.userAgent,b='未知';
        if(ua.indexOf('Edg')>-1)b='Microsoft Edge';
        else if(ua.indexOf('Chrome')>-1)b='Google Chrome';
        else if(ua.indexOf('Firefox')>-1)b='Mozilla Firefox';
        else if(ua.indexOf('Safari')>-1&&ua.indexOf('Chrome')===-1)b='Apple Safari';
        else if(ua.indexOf('Opera')>-1)b='Opera';
        document.getElementById('browserInfo').textContent=b;
        document.getElementById('screenInfo').textContent=screen.width+'x'+screen.height+' · '+(navigator.language||'未知');
    })();
    (function(){
        try{var tz='__TIMEZONE__';if(tz&&tz!=='未知'){var now=new Date();var opts={timeZone:tz,hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'};document.getElementById('localTime').textContent='本地时间: '+now.toLocaleString('zh-CN',opts)}}catch(e){}
    })();
    function codeToFlag(code) {
        if (!code || code.length !== 2) return '🏁';
        var offset = 127397;
        return String.fromCodePoint(code.charCodeAt(0)+offset)+String.fromCodePoint(code.charCodeAt(1)+offset);
    }
    function copyIP(){navigator.clipboard.writeText('__IP__').then(function(){showToast('✅ IP地址已复制')})}
    function copyAll(){
        var data=__JSON_RAW__,t='IP地址: '+data.ip+'\\n';
        if(data.location){var l=data.location;t+='国家: '+l.country+' ('+l.country_code+')\\n';t+='城市: '+l.city+'\\n';t+='地区: '+(l.region_name||'未知')+'\\n';t+='经纬度: '+l.latitude+', '+l.longitude+'\\n';t+='时区: '+l.timezone+'\\n';t+='ISP: '+l.isp+'\\n';t+='AS: '+(l.as||'未知')+'\\n'}
        navigator.clipboard.writeText(t).then(function(){showToast('✅ 全部信息已复制')})
    }
    function showToast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}
    function toggleJSON(b){b.classList.toggle('open');document.getElementById('jsonContent').classList.toggle('show')}
    
    // Live visitors on homepage
    function loadLive(){
      fetch('/api/stats').then(function(r){return r.json();}).then(function(d){
        var el=document.getElementById('lvList');if(!el||!d.recent||!d.recent.length){var sec=document.getElementById('liveVisitors');if(sec)sec.style.display='none';return;}
        var sec=document.getElementById('liveVisitors');if(sec)sec.style.display='';
        el.innerHTML=d.recent.slice(0,8).reverse().map(function(v){
          var fl='';try{if(v.country_code&&v.country_code.length===2){var o=127397;fl=String.fromCodePoint(v.country_code.charCodeAt(0)+o)+String.fromCodePoint(v.country_code.charCodeAt(1)+o);}}catch(e){}
          var ago=Math.round((Date.now()-new Date(v.time).getTime())/60000);
          return '<div class="lv-card"><div class="lv-card-top"><span class="lv-flag">'+(fl||'🌐')+'</span><span class="lv-ip">'+v.ip+'</span><span class="lv-live"></span></div><div class="lv-loc">'+(v.city||'?')+', '+(v.country||'?')+'</div><div class="lv-time">'+(ago<1?'刚刚':ago+'分钟前')+'</div></div>';
        }).join('');
      }).catch(function(){});
    }
    loadLive();setInterval(loadLive,15000);
</script>
</body>
</html>"""


# ========== 管理员后台模板 ==========
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IP Detector - Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#0a0e27;color:#e8eaf6;min-height:100vh}
.login-wrap{display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:#111640;border:1px solid rgba(124,77,255,.3);border-radius:20px;padding:40px;width:360px;text-align:center}
.login-box h2{margin-bottom:24px;font-size:22px}
.login-box input{width:100%;padding:14px;border-radius:12px;border:1px solid rgba(124,77,255,.3);background:rgba(255,255,255,.05);color:#e8eaf6;font-size:16px;outline:none;margin-bottom:16px}
.login-box input:focus{border-color:#7c4dff}
.login-box button{width:100%;padding:14px;border-radius:12px;border:none;background:linear-gradient(135deg,#7c4dff,#448aff);color:#fff;font-size:16px;font-weight:600;cursor:pointer}
.login-box button:disabled{opacity:.5;cursor:not-allowed}
.err{color:#ff5252;font-size:13px;margin-top:8px;display:none}
.admin-wrap{display:none;padding:20px;max-width:1200px;margin:0 auto}
.admin-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:10px}
.admin-header h2{font-size:20px}
.header-btns{display:flex;gap:8px}
.btn{padding:8px 16px;border-radius:10px;border:1px solid rgba(124,77,255,.3);background:rgba(255,255,255,.05);color:#9fa8da;cursor:pointer;font-size:13px}
.btn:hover{border-color:#7c4dff;color:#7c4dff}
.btn-danger{border-color:rgba(255,82,82,.3);color:#ff5252}.btn-danger:hover{background:rgba(255,82,82,.15)}
.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.stat{background:#111640;border:1px solid rgba(124,77,255,.2);border-radius:12px;padding:16px;text-align:center}
.stat .num{font-size:28px;font-weight:800;background:linear-gradient(135deg,#7c4dff,#448aff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat .lbl{font-size:11px;color:#5c6bc0;text-transform:uppercase;letter-spacing:1px;margin-top:4px}
.rt-bar{background:rgba(105,240,174,.08);border:1px solid rgba(105,240,174,.2);border-radius:10px;padding:10px 16px;margin-bottom:16px;display:flex;align-items:center;gap:8px;font-size:13px}
.rt-dot{width:8px;height:8px;border-radius:50%;background:#69f0ae;animation:bk 1.5s infinite}
@keyframes bk{0%,100%{opacity:1}50%{opacity:.3}}
.filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.filters input,.filters select{padding:8px 12px;border-radius:10px;border:1px solid rgba(124,77,255,.2);background:rgba(255,255,255,.05);color:#e8eaf6;font-size:13px;outline:none}
.filters select option{background:#111640}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;padding:10px 8px;border-bottom:1px solid rgba(124,77,255,.2);color:#5c6bc0;font-size:11px;text-transform:uppercase;letter-spacing:1px}
.tbl td{padding:10px 8px;border-bottom:1px solid rgba(255,255,255,.03)}
.tbl tr:hover{background:rgba(124,77,255,.05)}
.btn-sm{padding:4px 10px;border-radius:6px;border:1px solid rgba(124,77,255,.3);background:transparent;color:#9fa8da;cursor:pointer;font-size:12px}
.btn-sm:hover{border-color:#7c4dff;color:#7c4dff}
.pager{display:flex;gap:6px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.pager button{padding:6px 12px;border-radius:8px;border:1px solid rgba(124,77,255,.2);background:transparent;color:#9fa8da;cursor:pointer;font-size:13px}
.pager button.on{background:#7c4dff;color:#fff;border-color:#7c4dff}
.pager button:disabled{opacity:.3;cursor:not-allowed}
.modal-bg{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);justify-content:center;align-items:center;z-index:999}
.modal{background:#111640;border:1px solid rgba(124,77,255,.3);border-radius:16px;padding:24px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto}
.modal h3{margin-bottom:16px}.modal p{margin:8px 0;font-size:14px;color:#9fa8da}
.modal-close{display:block;margin-top:16px;padding:10px 20px;border-radius:10px;border:none;background:#7c4dff;color:#fff;cursor:pointer;width:100%}
</style>
</head>
<body>
<div id="loginWrap" class="login-wrap">
  <div class="login-box">
    <h2>Admin Login</h2>
    <input type="password" id="pwdInput" placeholder="Enter password">
    <button id="loginBtn" onclick="doLogin()">Login</button>
    <div id="errMsg" class="err"></div>
  </div>
</div>
<div id="adminWrap" class="admin-wrap">
  <div class="admin-header">
    <h2>IP Access Dashboard</h2>
    <div class="header-btns">
      <button class="btn" onclick="loadData()">Refresh</button>
      <button class="btn" onclick="doExport()">CSV</button>
      <button class="btn btn-danger" onclick="doLogout()">Logout</button>
    </div>
  </div>
  <div class="rt-bar"><span class="rt-dot"></span><span id="rtText">Loading...</span></div>
  <div id="statsRow" class="stats-row"></div>
  <div class="filters">
    <input id="searchBox" placeholder="Search IP/city..." oninput="doFilter()">
    <select id="countrySel" onchange="doFilter()"><option value="">All Countries</option></select>
  </div>
  <table class="tbl">
    <thead><tr><th>#</th><th>IP</th><th>Country</th><th>City</th><th>ISP</th><th>Time</th><th>Act</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <div id="pager" class="pager"></div>
</div>
<div id="detailModal" class="modal-bg" onclick="if(event.target===this)this.style.display='none'">
  <div class="modal"><h3 id="detailTitle"></h3><div id="detailBody"></div>
  <button class="modal-close" onclick="document.getElementById('detailModal').style.display='none'">Close</button></div>
</div>
<script>
var ALL=[],FILT=[],PG=1,PS=30,BUSY=false;
function ck(n){try{var m=document.cookie.match(new RegExp("(^| )"+n+"=([^;]+)"));return m?m[2]:"";}catch(e){return "";}}
function sk(n,v){document.cookie=n+"="+v+";path=/;max-age=86400;SameSite=Lax";}
function dk(n){document.cookie=n+"=;path=/;max-age=0;SameSite=Lax";}
function fl(cc){if(!cc||cc.length!==2)return "";try{return String.fromCodePoint(cc.charCodeAt(0)+127397)+String.fromCodePoint(cc.charCodeAt(1)+127397);}catch(e){return "";}}
function doLogin(){
  var p=document.getElementById("pwdInput"),e=document.getElementById("errMsg"),b=document.getElementById("loginBtn");
  if(!p||!e||!b)return;
  var pw=p.value.trim();
  if(!pw){e.textContent="Please enter password";e.style.display="block";return;}
  e.style.display="none";b.disabled=true;b.textContent="Logging in...";
  fetch("/api/admin/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:pw})})
  .then(function(r){return r.json();})
  .then(function(d){
    b.disabled=false;b.textContent="Login";
    if(d.token){sk("ip_detect_admin",d.token);enterAdmin();}
    else{e.textContent=d.message||"Login failed";e.style.display="block";}
  })
  .catch(function(x){b.disabled=false;b.textContent="Login";e.textContent="Error: "+x.message;e.style.display="block";});
}
function doLogout(){dk("ip_detect_admin");location.reload();}
function enterAdmin(){
  var lw=document.getElementById("loginWrap"),aw=document.getElementById("adminWrap");
  if(lw)lw.style.display="none";if(aw)aw.style.display="block";
  loadData();setInterval(loadData,30000);
}
function loadData(){
  var t=ck("ip_detect_admin");if(!t){doLogout();return;}if(BUSY)return;BUSY=true;
  fetch("/api/admin/visits",{headers:{"Authorization":"Bearer "+t}})
  .then(function(r){if(r.status===401){doLogout();return null;}return r.json();})
  .then(function(d){BUSY=false;if(!d)return;ALL=(d.visits||[]).slice().reverse();doFilter();renderStats();renderRT();})
  .catch(function(){BUSY=false;});
}
function renderRT(){
  var now=Date.now(),h1=0,m5=0;
  for(var i=0;i<ALL.length;i++){if(ALL[i].time){var df=now-new Date(ALL[i].time).getTime();if(df<3600000)h1++;if(df<300000)m5++;}}
  var el=document.getElementById("rtText");var last=ALL[0];
  if(el)el.textContent="1h: "+h1+" | 5m: "+m5+(last?" | Last: "+fl(last.country_code)+" "+last.ip+" "+(last.city||""):"");
}
function renderStats(){
  var el=document.getElementById("statsRow");if(!el)return;
  var total=ALL.length,today=new Date().toISOString().slice(0,10),td=0;
  for(var i=0;i<ALL.length;i++){if(ALL[i].time&&ALL[i].time.startsWith(today))td++;}
  var uniq=new Set(ALL.map(function(v){return v.ip})).size;
  var cn=new Set(ALL.map(function(v){return v.country}).filter(function(c){return c&&c!=="Unknown"&&c!==""})).size;
  el.innerHTML='<div class="stat"><div class="num">'+total+'</div><div class="lbl">Total</div></div><div class="stat"><div class="num">'+td+'</div><div class="lbl">Today</div></div><div class="stat"><div class="num">'+uniq+'</div><div class="lbl">Unique IPs</div></div><div class="stat"><div class="num">'+cn+'</div><div class="lbl">Countries</div></div>';
}
function doFilter(){
  var q=(document.getElementById("searchBox")||{}).value||"",qL=q.toLowerCase();
  var cc=(document.getElementById("countrySel")||{}).value||"";
  FILT=ALL.filter(function(v){if(cc&&v.country!==cc)return false;if(qL){var h=(v.ip||"")+(v.city||"")+(v.country||"")+(v.isp||"");if(h.toLowerCase().indexOf(qL)<0)return false;}return true;});
  PG=1;renderTable();buildCountries();
}
function buildCountries(){
  var cs={};ALL.forEach(function(v){if(v.country)cs[v.country]=1;});
  var el=document.getElementById("countrySel");if(!el)return;var cur=el.value;
  el.innerHTML='<option value="">All Countries</option>';
  Object.keys(cs).sort().forEach(function(c){var found=ALL.find(function(v){return v.country===c});var opt=document.createElement("option");opt.value=c;opt.textContent=fl(found?found.country_code:"")+" "+c;el.appendChild(opt);});
  el.value=cur;
}
function renderTable(){
  var tb=document.getElementById("tbody");if(!tb)return;
  var total=FILT.length,pages=Math.ceil(total/PS)||1;if(PG>pages)PG=pages;
  var s=(PG-1)*PS,data=FILT.slice(s,s+PS);
  tb.innerHTML=data.map(function(v,i){return '<tr><td>'+(s+i+1)+'</td><td>'+v.ip+'</td><td>'+fl(v.country_code)+' '+(v.country||"")+'</td><td>'+(v.city||"-")+'</td><td>'+(v.isp||"-").substring(0,20)+'</td><td style="font-size:12px">'+(v.time?new Date(v.time).toLocaleString():"-")+'</td><td><button class="btn-sm" onclick="showDetail('+(s+i)+')">Info</button></td></tr>';}).join("");
  var pg=document.getElementById("pager");if(!pg)return;
  var h='<button onclick="goPg('+(PG-1)+')" '+(PG===1?"disabled":"")+'>Prev</button>';
  for(var p=Math.max(1,PG-3),ep=Math.min(pages,PG+3);p<=ep;p++){h+='<button class="'+(p===PG?"on":"")+'" onclick="goPg('+p+')">'+p+'</button>';}
  h+='<button onclick="goPg('+(PG+1)+')" '+(PG===pages?"disabled":"")+'>Next</button>';
  pg.innerHTML=h;
}
function goPg(p){PG=p;renderTable();}
function showDetail(idx){
  var v=FILT[idx];if(!v)return;
  var t=document.getElementById("detailTitle"),b=document.getElementById("detailBody");
  if(t)t.textContent=v.ip;if(b)b.innerHTML='<p>'+fl(v.country_code)+' '+(v.country||"-")+'</p><p>'+(v.city||"-")+'</p><p>'+(v.region||"-")+'</p><p>'+(v.isp||"-")+'</p><p>'+(v.time?new Date(v.time).toLocaleString():"-")+'</p><p>'+(v.latitude||0)+', '+(v.longitude||0)+'</p>';
  document.getElementById("detailModal").style.display="flex";
}
function doExport(){
  if(!ALL.length){alert("No data");return;}
  var rows=["IP,Country,City,ISP,Time,Lat,Lon"];
  ALL.forEach(function(v){rows.push((v.ip||"")+","+(v.country||"")+","+(v.city||"")+","+(v.isp||"")+","+(v.time||"")+","+(v.latitude||"")+","+(v.longitude||""));});
  var blob=new Blob([rows.join(String.fromCharCode(10))],{type:"text/csv"});
  var a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="ip-visits.csv";a.click();
}
document.getElementById("pwdInput").addEventListener("keydown",function(ev){if(ev.key==="Enter")doLogin();});
(function(){var t=ck("ip_detect_admin");if(t){fetch("/api/admin/visits",{headers:{"Authorization":"Bearer "+t}}).then(function(r){if(r.ok){enterAdmin();}else{dk("ip_detect_admin");}}).catch(function(){});}})();
</script>
</body>
</html>"""






# ========== 路由 ==========

@app.on_event("startup")
async def startup():
    try: _load_visits()
    except Exception: pass


@app.get("/", response_class=HTMLResponse)
async def get_ip_info(request: Request):
    ip = _get_client_ip(request)
    location = await _fetch_location(ip)
    ua = request.headers.get("user-agent", "")
    referer = request.headers.get("referer", "")
    _record_visit(ip, location, ua, referer)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    country_flag = get_country_flag(location.get("country_code", ""))
    lat = location.get("latitude", 0)
    lon = location.get("longitude", 0)
    try:
        d = 0.05
        lat_f, lon_f = float(lat), float(lon)
        map_bbox = f"{lon_f-d},{lat_f-d},{lon_f+d},{lat_f+d}"
    except (ValueError, TypeError):
        map_bbox = "112.5,37.8,112.6,37.9"

    json_data = {"ip": ip, "location": location or None, "error": None}
    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
    json_raw = json.dumps(json_data, ensure_ascii=False)

    html = HTML_TEMPLATE
    for old, new in [
        ("__IP__", ip), ("__TIMESTAMP__", timestamp),
        ("__COUNTRY_FLAG__", country_flag),
        ("__COUNTRY__", location.get("country", "未知")),
        ("__COUNTRY_CODE__", location.get("country_code", "未知")),
        ("__CITY__", location.get("city", "未知")),
        ("__REGION__", location.get("region_name", "未知")),
        ("__REGION_NAME__", location.get("region_name", "未知")),
        ("__LAT__", str(lat)), ("__LON__", str(lon)),
        ("__TIMEZONE__", location.get("timezone", "未知")),
        ("__ISP__", location.get("isp", "未知")),
        ("__AS__", location.get("as", "未知")),
        ("__ZIP__", location.get("zip", "未知")),
        ("__MAP_BBOX__", map_bbox),
        ("__JSON_DATA__", json_str.replace("<", "&lt;").replace(">", "&gt;")),
        ("__JSON_RAW__", json_raw),
    ]:
        html = html.replace(old, new)
    return HTMLResponse(content=html)


@app.get("/api/info")
async def get_info_api(request: Request):
    ip = _get_client_ip(request)
    location = await _fetch_location(ip)
    return {"ip": ip, "location": location or None, "error": None}


@app.get("/api/query")
async def query_ip(ip: str = Query(...)):
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return {"error": "IP格式错误", "ip": ip, "location": None}
    try:
        for p in parts:
            if not 0 <= int(p) <= 255:
                return {"error": "IP格式错误", "ip": ip, "location": None}
    except ValueError:
        return {"error": "IP格式错误", "ip": ip, "location": None}
    location = await _fetch_location(ip)
    if not location:
        return {"error": "查询失败", "ip": ip, "location": None}
    return {"ip": ip, "location": location, "error": None}


@app.get("/api/stats")
async def get_stats():
    visits = _load_visits()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()
    ips, countries, recent1h = {}, {}, 0
    for v in visits:
        ips[v.get("ip", "")] = 1
        cc = v.get("country_code", "")
        if cc: countries[cc] = countries.get(cc, 0) + 1
        if v.get("time"):
            try:
                t = datetime.strptime(v["time"], "%Y-%m-%d %H:%M:%S")
                if (now - t).total_seconds() < 3600:
                    recent1h += 1
            except Exception:
                pass
    return {
        "total": len(visits),
        "today": sum(1 for v in visits if v.get("time", "").startswith(today)),
        "unique_ips": len(ips),
        "unique_countries": len(countries),
        "recent_1h": recent1h,
        "recent": [v for v in visits if v.get("time") and (now - datetime.strptime(v["time"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 3600][-10:],
    }


@app.get("/api/version")
async def get_version():
    return {"version": "9.4.0", "name": "IP Detector"}




@app.get("/api/events")
async def sse_events(request: Request):
    async def gen():
        last_count = len(_load_visits())
        for _ in range(120):
            await asyncio.sleep(1)
            current = len(_load_visits())
            if current > last_count:
                visits = _load_visits()
                if visits:
                    v = visits[-1]
                    data = json.dumps({"ip": v.get("ip",""), "city": v.get("city",""), "country": v.get("country",""), "country_code": v.get("country_code",""), "time": v.get("time","")}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                last_count = current
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ========== 管理员API ==========

def _verify_admin(request: Request) -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            decoded = base64.b64decode(token).decode("utf-8")
            return decoded == ADMIN_PASSWORD
        except Exception:
            return False
    return False


@app.post("/api/admin/login")
async def admin_login(request: Request):
    try:
        body = await request.json()
        pwd = body.get("password", "")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request")
    if pwd != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")
    token = base64.b64encode(pwd.encode("utf-8")).decode("utf-8")
    return {"success": True, "token": token, "message": "登录成功"}


@app.get("/api/admin/visits")
async def admin_get_visits(request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")
    visits = _load_visits()
    return {"visits": visits, "total": len(visits)}


@app.delete("/api/admin/visits/{ip}")
async def admin_delete_visit(ip: str, request: Request):
    """删除指定IP的访问记录（删除最近一条）"""
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")
    visits = _load_visits()
    for i in range(len(visits)-1, -1, -1):
        if visits[i].get("ip") == ip:
            visits.pop(i)
            _save_visits(visits, force=True)
            return {"message": "已删除", "ip": ip}
    raise HTTPException(status_code=404, detail="未找到记录")


@app.post("/api/admin/clear")
async def admin_clear_visits(request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")
    _save_visits([], force=True)
    return {"message": "已清空"}


@app.delete("/api/admin/visits")
async def admin_clear_all_visits(request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")
    _save_visits([], force=True)
    return {"message": "已清空"}




@app.delete("/api/admin/visits/index/{idx}")
async def admin_delete_by_index(idx: int, request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")
    visits = _load_visits()
    # idx is from the reversed list, convert to actual index
    actual_idx = len(visits) - 1 - idx
    if 0 <= actual_idx < len(visits):
        visits.pop(actual_idx)
        _save_visits(visits, force=True)
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="未找到记录")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(content=ADMIN_HTML)


@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name": "IP位置检测", "short_name": "IP定位", "start_url": "/",
        "display": "standalone", "background_color": "#0a0e27", "theme_color": "#7c4dff",
        "icons": [{"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌍</text></svg>", "sizes": "any", "type": "image/svg+xml"}]
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
