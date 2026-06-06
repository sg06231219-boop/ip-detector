from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx
import os
import json
import io
import csv
import time
import base64
from datetime import datetime
from typing import Optional, Dict, Any

app = FastAPI()

# ========== 閰嶇疆 ==========
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Lys13579")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = "sg06231219-boop/ip-detector"
GITHUB_BRANCH = "data"
VISITS_PATH = "data/visits.json"

# 鍐欏叆鑺傛祦锛氱疮绉疦娆″彉鏇村悗鎵嶇湡姝ｆ帹閫佸埌GitHub锛岄伩鍏嶉绻乧ommit
_pending_saves = 0
_SAVE_THRESHOLD = 5  # 姣?娆¤闂墠鎺ㄩ€佷竴娆?_last_save_time = 0.0
_SAVE_INTERVAL = 120  # 鑷冲皯闂撮殧120绉掓帹閫?
# ========== IP浣嶇疆缂撳瓨锛堝唴瀛橈紝1灏忔椂TTL锛?==========
_location_cache: Dict[str, Any] = {}
_location_cache_ttl: Dict[str, float] = {}
LOCATION_CACHE_TTL = 3600  # 1灏忔椂

# ========== 鏁版嵁瀛樺偍锛圙itHub Contents API 鎸佷箙鍖栵級 ==========
def _github_get_visits() -> list:
    """浠嶨itHub浠撳簱璇诲彇visits.json"""
    try:
        headers = {
            "Authorization": f"token {GITHUB_PAT}",
            "Accept": "application/vnd.github.v3+json"
        }
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_PATH}?ref={GITHUB_BRANCH}"
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            visits = json.loads(content)
            return visits if isinstance(visits, list) else []
    except Exception:
        pass
    return []

def _github_save_visits(visits: list) -> bool:
    """淇濆瓨visits.json鍒癎itHub浠撳簱"""
    try:
        headers = {
            "Authorization": f"token {GITHUB_PAT}",
            "Accept": "application/vnd.github.v3+json"
        }
        # 鍏堣幏鍙栧綋鍓嶆枃浠秙ha
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_PATH}?ref={GITHUB_BRANCH}"
        resp = httpx.get(url, headers=headers, timeout=10)
        sha = resp.json().get("sha") if resp.status_code == 200 else None

        content = base64.b64encode(
            json.dumps(visits, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        body = {
            "message": f"Update visits.json ({len(visits)} records)",
            "content": content,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            body["sha"] = sha
        resp = httpx.put(url, headers=headers, json=body, timeout=15)
        return resp.status_code in (200, 201)
    except Exception:
        pass
    return False

# 鍐呭瓨缂撳瓨锛堥伩鍏嶆瘡娆¤姹傞兘璇籊itHub锛?_visits_cache: list = []
_visits_cache_time: float = 0
_VISITS_CACHE_TTL = 30  # 30绉掔紦瀛?
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
    # 闄愬埗鏈€澶?000鏉?    if len(visits) > 2000:
        visits = visits[-2000:]
    _visits_cache = visits
    _visits_cache_time = time.time()
    _pending_saves += 1
    now = time.time()
    # 鑺傛祦锛氱疮绉?娆″彉鏇存垨瓒呰繃120绉掓墠鎺ㄩ€侊紝绠＄悊鍛樻搷浣?force=True)绔嬪嵆鎺ㄩ€?    should_push = force or _pending_saves >= _SAVE_THRESHOLD or (now - _last_save_time) >= _SAVE_INTERVAL
    if should_push:
        _pending_saves = 0
        _last_save_time = now
        _github_save_visits(visits)

def _record_visit(ip: str, location: dict, user_agent: str = "", referer: str = ""):
    """璁板綍璁块棶锛屽悓IP 5鍒嗛挓鍐呭幓閲?""
    visits = _load_visits()
    now = datetime.now()
    for v in reversed(visits[-50:]):  # 鍙鏌ユ渶杩?0鏉?        if v.get("ip") == ip:
            try:
                last_time = datetime.strptime(v["time"], "%Y-%m-%d %H:%M:%S")
                if (now - last_time).total_seconds() < 300:
                    return v
            except Exception:
                pass
    visit = {
        "ip": ip,
        "country": location.get("country", "鏈煡"),
        "country_code": location.get("country_code", ""),
        "city": location.get("city", "鏈煡"),
        "region": location.get("region_name", "鏈煡"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "timezone": location.get("timezone", "鏈煡"),
        "isp": location.get("isp", "鏈煡"),
        "as": location.get("as", "鏈煡"),
        "user_agent": user_agent[:200] if user_agent else "",
        "referer": referer[:200] if referer else "",
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    visits.append(visit)
    _save_visits(visits)
    return visit

def _delete_visit(index: int):
    """鍒犻櫎鎸囧畾绱㈠紩鐨勮闂褰?""
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
    """鏌ヨIP鍦扮悊浣嶇疆锛堝甫鍐呭瓨缂撳瓨锛?""
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
                        "country": data.get("country", "鏈煡"),
                        "country_code": data.get("countryCode", "鏈煡"),
                        "city": data.get("city", "鏈煡"),
                        "latitude": data.get("lat", "鏈煡"),
                        "longitude": data.get("lon", "鏈煡"),
                        "timezone": data.get("timezone", "鏈煡"),
                        "isp": data.get("isp", "鏈煡"),
                        "as": data.get("as", "鏈煡"),
                        "region_name": data.get("regionName", "鏈煡"),
                        "zip": data.get("zip", "鏈煡"),
                    }
                    _location_cache[cache_key] = result
                    _location_cache_ttl[cache_key] = now
                    return result
    except Exception:
        pass
    return {}

def get_country_flag(code: str) -> str:
    if not code or len(code) != 2:
        return "馃弫"
    try:
        offset = 127397
        return chr(ord(code[0].upper()) + offset) + chr(ord(code[1].upper()) + offset)
    except Exception:
        return "馃弫"


# ========== 鍓嶅彴椤甸潰妯℃澘 ==========
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IP浣嶇疆妫€娴?- 鏅鸿兘瀹氫綅宸ュ叿</title>
    <meta name="description" content="涓€閿娴嬫偍鐨処P鍦板潃銆佸湴鐞嗕綅缃€両SP淇℃伅銆傚厤璐广€佸揩閫熴€佺簿鍑嗙殑IP瀹氫綅宸ュ叿銆?>
    <meta name="keywords" content="IP瀹氫綅,IP鏌ヨ,IP鍦板潃鏌ヨ,鍦扮悊浣嶇疆,IP妫€娴?>
    <meta property="og:title" content="IP浣嶇疆妫€娴?- 鏅鸿兘瀹氫綅宸ュ叿">
    <meta property="og:description" content="涓€閿娴嬫偍鐨処P鍦板潃銆佸湴鐞嗕綅缃€両SP淇℃伅锛屽厤璐逛娇鐢?>
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://ip-detector-lu2p.onrender.com">
    <meta name="twitter:card" content="summary">
    <meta name="theme-color" content="#0a0e27">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>馃實</text></svg>">
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
    </style>
</head>
<body>
    <canvas id="particles"></canvas>
    <div class="wrapper">
        <div class="topbar">
            <button onclick="toggleTheme()" id="themeBtn">馃寵</button>
            <button onclick="sharePage()">馃敆 鍒嗕韩</button>
        </div>
        <div class="header">
            <h1>馃實 IP 鏅鸿兘瀹氫綅</h1>
            <p>瀹炴椂妫€娴嬫偍鐨勭綉缁滆韩浠戒笌鍦扮悊浣嶇疆</p>
            <div class="social-proof">宸叉湁 <span id="totalUsers">-</span> 浜轰娇鐢?/div>
            <div class="status-badge">
                <span class="status-dot"></span>
                妫€娴嬪畬鎴?路 __TIMESTAMP__
            </div>
        </div>
        <div class="query-section">
            <div class="query-box">
                <input type="text" id="queryInput" placeholder="杈撳叆浠绘剰IP鍦板潃鏌ヨ浣嶇疆锛屼緥濡傦細8.8.8.8" onkeydown="if(event.key==='Enter')queryIP()">
                <button onclick="queryIP()" id="queryBtn">馃攳 鏌ヨIP</button>
            </div>
            <div id="queryResult"></div>
        </div>
        <div class="ip-hero">
            <div class="ip-label">鎮ㄧ殑鍏綉 IP 鍦板潃</div>
            <div class="ip-value" onclick="copyIP()" title="鐐瑰嚮澶嶅埗">__IP__</div>
            <div class="copy-hint">鐐瑰嚮IP鍗冲彲澶嶅埗</div>
        </div>
        <div class="info-grid" id="infoGrid">
            <div class="info-card card-location">
                <div class="card-header"><div class="card-icon">馃彸锔?/div><div class="card-title">鍥藉/鍦板尯</div></div>
                <div class="card-value">__COUNTRY_FLAG__ __COUNTRY__</div>
                <div class="card-sub">浠ｇ爜: __COUNTRY_CODE__</div>
            </div>
            <div class="info-card card-city">
                <div class="card-header"><div class="card-icon">馃彊锔?/div><div class="card-title">鍩庡競</div></div>
                <div class="card-value">__CITY__</div>
                <div class="card-sub">鍦板尯: __REGION__</div>
            </div>
            <div class="info-card card-coords">
                <div class="card-header"><div class="card-icon">馃椇锔?/div><div class="card-title">缁忕含搴?/div></div>
                <div class="card-value">__LAT__, __LON__</div>
                <div class="card-sub">WGS84鍧愭爣绯?/div>
            </div>
            <div class="info-card card-timezone">
                <div class="card-header"><div class="card-icon">鈴?/div><div class="card-title">鏃跺尯</div></div>
                <div class="card-value">__TIMEZONE__</div>
                <div class="card-sub" id="localTime">鏈湴鏃堕棿: 鍔犺浇涓?..</div>
            </div>
            <div class="info-card card-isp">
                <div class="card-header"><div class="card-icon">馃寪</div><div class="card-title">ISP 杩愯惀鍟?/div></div>
                <div class="card-value">__ISP__</div>
                <div class="card-sub">浜掕仈缃戞湇鍔℃彁渚涘晢</div>
            </div>
            <div class="info-card card-as">
                <div class="card-header"><div class="card-icon">馃敆</div><div class="card-title">AS 缂栧彿</div></div>
                <div class="card-value" style="font-size:16px;">__AS__</div>
                <div class="card-sub">鑷不绯荤粺缂栧彿</div>
            </div>
            <div class="info-card card-region">
                <div class="card-header"><div class="card-icon">馃搷</div><div class="card-title">绮剧‘鍖哄煙</div></div>
                <div class="card-value" style="font-size:16px;">__REGION_NAME__</div>
                <div class="card-sub">閭紪: __ZIP__</div>
            </div>
            <div class="info-card card-browser">
                <div class="card-header"><div class="card-icon">馃枼锔?/div><div class="card-title">鎮ㄧ殑娴忚鍣?/div></div>
                <div class="card-value" style="font-size:14px;" id="browserInfo">妫€娴嬩腑...</div>
                <div class="card-sub" id="screenInfo"></div>
            </div>
        </div>
        <div class="map-section">
            <h3>馃搷 鍦扮悊浣嶇疆鍙鍖?/h3>
            <div class="map-container">
                <iframe id="mapFrame" src="https://www.openstreetmap.org/export/embed.html?bbox=__MAP_BBOX__&layer=mapnik&marker=__LAT__,__LON__" loading="lazy"></iframe>
            </div>
        </div>
        <div class="actions">
            <a href="https://www.google.com/maps?q=__LAT__,__LON__" target="_blank" class="btn btn-primary">馃椇锔?Google鍦板浘鏌ョ湅</a>
            <button class="btn btn-secondary" onclick="copyAll()">馃搵 澶嶅埗鍏ㄩ儴淇℃伅</button>
            <button class="btn btn-success" onclick="copyIP()">馃搶 澶嶅埗IP鍦板潃</button>
        </div>
        <div class="json-section">
            <button class="json-toggle" onclick="toggleJSON(this)">
                <span class="arrow">鈻?/span> 鏌ョ湅 JSON 鍘熷鏁版嵁
            </button>
            <div class="json-content" id="jsonContent">__JSON_DATA__</div>
        </div>
        <div class="footer">
            IP鏅鸿兘瀹氫綅宸ュ叿 路 鏁版嵁鏉ユ簮 ip-api.com 路 妫€娴嬫椂闂?__TIMESTAMP__<br>
            <span style="opacity:0.5;">浣嶇疆涓哄ぇ鑷翠及绠楋紝涓嶄唬琛ㄧ簿纭綇鍧€</span><br>
            <a href="/admin" style="color:var(--text-muted);font-size:11px;margin-top:4px;display:inline-block">馃敀 绠＄悊鍚庡彴</a>
        </div>
    </div>
    <div class="toast" id="toast"></div>
    <script>
    (function(){
        var saved = localStorage.getItem('ip-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        document.getElementById('themeBtn').textContent = saved === 'dark' ? '鈽€锔? : '馃寵';
    })();
    function toggleTheme() {
        var cur = document.documentElement.getAttribute('data-theme') || 'dark';
        var next = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('ip-theme', next);
        document.getElementById('themeBtn').textContent = next === 'dark' ? '鈽€锔? : '馃寵';
    }
    function sharePage() {
        var url = location.href;
        if (navigator.share) {
            navigator.share({ title: 'IP鏅鸿兘瀹氫綅', text: '鎴戠殑IP: __IP__', url: url }).catch(function(){});
        } else {
            navigator.clipboard.writeText(url).then(function(){ showToast('鉁?閾炬帴宸插鍒?); });
        }
    }
    // 绀句細璇佹槑 - 鍔犺浇浣跨敤浜烘暟
    fetch('/api/stats').then(function(r){return r.json()}).then(function(d){
        document.getElementById('totalUsers').textContent = d.total || 0;
    }).catch(function(){});

    var queryCache = {};
    function queryIP() {
        var input = document.getElementById('queryInput');
        var btn = document.getElementById('queryBtn');
        var ip = input.value.trim();
        if (!ip) { showToast('鈿狅笍 璇疯緭鍏P鍦板潃'); return; }
        var ipRe = /^(\d{1,3}\.){3}\d{1,3}$/;
        if (!ipRe.test(ip)) { showToast('鈿狅笍 IP鏍煎紡涓嶆纭?); return; }
        btn.disabled = true; btn.textContent = '鏌ヨ涓?..';
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        fetch('/api/query?ip=' + encodeURIComponent(ip))
            .then(function(r){ return r.json(); })
            .then(function(d){
                btn.disabled = false; btn.textContent = '馃攳 鏌ヨIP';
                if (d.error) { showToast('鉂?' + d.error); return; }
                var l = d.location || {};
                var flag = codeToFlag(l.country_code || '');
                var lat = l.latitude || 0, lon = l.longitude || 0;
                var mapBBox = '';
                if (lat && lon) { var d2 = 0.05; mapBBox = (lon-d2) + ',' + (lat-d2) + ',' + (lon+d2) + ',' + (lat+d2); }
                var mapUrl = 'https://www.openstreetmap.org/export/embed.html?bbox=' + mapBBox + '&layer=mapnik&marker=' + lat + ',' + lon;
                var mapFilter = isDark ? 'invert(0.9) hue-rotate(180deg) brightness(0.9) contrast(1.1)' : 'none';
                var html = '<div class="query-result" style="margin-top:20px">' +
                    '<div class="ip-hero" style="margin:16px 0 20px">' +
                    '<div class="ip-label">鏌ヨ缁撴灉</div>' +
                    '<div class="ip-value" onclick="navigator.clipboard.writeText(\\''+ip+'\\').then(function(){showToast(\\'鉁?IP宸插鍒禱\')})">' + ip + '</div>' +
                    '</div>' +
                    '<div class="info-grid">' +
                    cardHTML('馃彸锔?,'鍥藉/鍦板尯', flag + ' ' + (l.country||'鏈煡'), '浠ｇ爜: ' + (l.country_code||'-')) +
                    cardHTML('馃彊锔?,'鍩庡競', (l.city||'鏈煡'), '鍦板尯: ' + (l.region_name||'鏈煡')) +
                    cardHTML('馃椇锔?,'缁忕含搴?, lat + ', ' + lon, 'WGS84鍧愭爣绯?) +
                    cardHTML('鈴?,'鏃跺尯', (l.timezone||'鏈煡'), '') +
                    cardHTML('馃寪','ISP', (l.isp||'鏈煡'), '') +
                    cardHTML('馃敆','AS缂栧彿', (l.as||'-'), '') +
                    cardHTML('馃搷','閭紪', (l.zip||'-'), '') +
                    '</div>' +
                    '<div class="map-section"><h3>馃搷 浣嶇疆鍙鍖?/h3>' +
                    '<div class="map-container"><iframe src="'+mapUrl+'" style="width:100%;height:100%;border:none;filter:'+mapFilter+'" loading="lazy"></iframe></div></div>' +
                    '<div class="actions">' +
                    '<a href="https://www.google.com/maps?q='+lat+','+lon+'" target="_blank" class="btn btn-primary">馃椇锔?Google鍦板浘</a>' +
                    '<button class="btn btn-success" onclick="navigator.clipboard.writeText(\\''+ip+'\\').then(function(){showToast(\\'鉁?IP宸插鍒禱\')})">馃搶 澶嶅埗IP</button>' +
                    '</div></div>';
                document.getElementById('queryResult').innerHTML = html;
            })
            .catch(function(err){ btn.disabled=false; btn.textContent='馃攳 鏌ヨIP'; showToast('鉂?鏌ヨ澶辫触'); });
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
        var ua=navigator.userAgent,b='鏈煡';
        if(ua.indexOf('Edg')>-1)b='Microsoft Edge';
        else if(ua.indexOf('Chrome')>-1)b='Google Chrome';
        else if(ua.indexOf('Firefox')>-1)b='Mozilla Firefox';
        else if(ua.indexOf('Safari')>-1&&ua.indexOf('Chrome')===-1)b='Apple Safari';
        else if(ua.indexOf('Opera')>-1)b='Opera';
        document.getElementById('browserInfo').textContent=b;
        document.getElementById('screenInfo').textContent=screen.width+'x'+screen.height+' 路 '+(navigator.language||'鏈煡');
    })();
    (function(){
        try{var tz='__TIMEZONE__';if(tz&&tz!=='鏈煡'){var now=new Date();var opts={timeZone:tz,hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'};document.getElementById('localTime').textContent='鏈湴鏃堕棿: '+now.toLocaleString('zh-CN',opts)}}catch(e){}
    })();
    function codeToFlag(code) {
        if (!code || code.length !== 2) return '馃弫';
        var offset = 127397;
        return String.fromCodePoint(code.charCodeAt(0)+offset)+String.fromCodePoint(code.charCodeAt(1)+offset);
    }
    function copyIP(){navigator.clipboard.writeText('__IP__').then(function(){showToast('鉁?IP鍦板潃宸插鍒?)})}
    function copyAll(){
        var data=__JSON_RAW__,t='IP鍦板潃: '+data.ip+'\\n';
        if(data.location){var l=data.location;t+='鍥藉: '+l.country+' ('+l.country_code+')\\n';t+='鍩庡競: '+l.city+'\\n';t+='鍦板尯: '+(l.region_name||'鏈煡')+'\\n';t+='缁忕含搴? '+l.latitude+', '+l.longitude+'\\n';t+='鏃跺尯: '+l.timezone+'\\n';t+='ISP: '+l.isp+'\\n';t+='AS: '+(l.as||'鏈煡')+'\\n'}
        navigator.clipboard.writeText(t).then(function(){showToast('鉁?鍏ㄩ儴淇℃伅宸插鍒?)})
    }
    function showToast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}
    function toggleJSON(b){b.classList.toggle('open');document.getElementById('jsonContent').classList.toggle('show')}
    </script>
</body>
</html>"""


# ========== 绠＄悊鍛樺悗鍙版ā鏉?==========
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>绠＄悊鍚庡彴 - IP浣嶇疆妫€娴?/title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>馃敀</text></svg>">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        :root {
            --bg-primary: #0a0e27; --bg-secondary: #111640; --bg-card: rgba(255,255,255,0.04);
            --bg-card-hover: rgba(255,255,255,0.08); --text-primary: #e8eaf6; --text-secondary: #9fa8da;
            --text-muted: #5c6bc0; --accent: #7c4dff; --accent2: #448aff; --accent3: #18ffff;
            --border: rgba(124,77,255,0.2); --success: #69f0ae; --danger: #ff5252; --warning: #ffd740;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; }
        .login-wrap { display:flex; justify-content:center; align-items:center; min-height:100vh; padding:20px; }
        .login-box { background:var(--bg-secondary); border:1px solid var(--border); border-radius:20px; padding:40px; max-width:400px; width:100%; text-align:center; }
        .login-box h2 { color:var(--accent3); margin-bottom:8px; font-size:24px; }
        .login-box p { color:var(--text-muted); font-size:13px; margin-bottom:24px; }
        .login-box input { width:100%; padding:14px 16px; border-radius:12px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-primary); font-size:15px; margin-bottom:16px; outline:none; transition:border-color 0.3s; }
        .login-box input:focus { border-color:var(--accent); }
        .login-box button { width:100%; padding:14px; border-radius:12px; border:none; background:linear-gradient(135deg,var(--accent),var(--accent2)); color:white; font-size:15px; font-weight:600; cursor:pointer; transition:transform 0.2s,box-shadow 0.2s; }
        .login-box button:hover { transform:translateY(-2px); box-shadow:0 8px 24px rgba(124,77,255,0.3); }
        .login-error { color:var(--danger); font-size:13px; margin-top:12px; display:none; }
        .admin-wrap { max-width:1400px; margin:0 auto; padding:20px; }
        .admin-header { display:flex; justify-content:space-between; align-items:center; padding:20px 0; border-bottom:1px solid var(--border); margin-bottom:24px; flex-wrap:wrap; gap:12px; }
        .admin-header h1 { font-size:22px; background:linear-gradient(135deg,var(--accent),var(--accent3)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
        .admin-header .actions { display:flex; gap:8px; flex-wrap:wrap; }
        .admin-btn { padding:8px 14px; border-radius:8px; border:none; cursor:pointer; font-size:13px; font-weight:600; transition:all 0.2s; }
        .btn-logout { background:rgba(255,82,82,0.15); color:var(--danger); border:1px solid rgba(255,82,82,0.3); }
        .btn-logout:hover { background:rgba(255,82,82,0.3); }
        .btn-refresh { background:rgba(105,240,174,0.15); color:var(--success); border:1px solid rgba(105,240,174,0.3); }
        .btn-refresh:hover { background:rgba(105,240,174,0.3); }
        .btn-danger { background:rgba(255,82,82,0.15); color:var(--danger); border:1px solid rgba(255,82,82,0.3); }
        .btn-danger:hover { background:rgba(255,82,82,0.3); }
        .btn-export { background:rgba(24,255,255,0.15); color:var(--accent3); border:1px solid rgba(24,255,255,0.3); }
        .btn-export:hover { background:rgba(24,255,255,0.3); }
        .live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--success); animation:pulse 2s infinite; margin-left:8px; }
        @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
        .stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:20px; }
        .stat-card { background:var(--bg-card); border:1px solid var(--border); border-radius:14px; padding:16px; text-align:center; }
        .stat-card .stat-value { font-size:28px; font-weight:800; background:linear-gradient(135deg,var(--accent3),var(--accent2)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
        .stat-card .stat-label { color:var(--text-muted); font-size:12px; margin-top:4px; }
        .viz-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }
        .viz-card { background:var(--bg-card); border:1px solid var(--border); border-radius:14px; padding:16px; }
        .viz-card h3 { font-size:13px; color:var(--text-secondary); margin-bottom:10px; }
        .viz-card canvas { width:100% !important; max-height:220px; }
        #adminMap { height:280px; border-radius:10px; }
        .toolbar { display:flex; gap:10px; margin-bottom:14px; flex-wrap:wrap; align-items:center; }
        .toolbar input, .toolbar select { padding:9px 13px; border-radius:9px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-primary); font-size:13px; outline:none; }
        .toolbar input:focus, .toolbar select:focus { border-color:var(--accent); }
        .toolbar input { flex:1; min-width:180px; }
        .table-wrap { background:var(--bg-card); border:1px solid var(--border); border-radius:14px; overflow:hidden; }
        table { width:100%; border-collapse:collapse; font-size:12px; }
        thead { background:rgba(124,77,255,0.1); }
        th { padding:12px 10px; text-align:left; color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:1px; border-bottom:1px solid var(--border); white-space:nowrap; }
        td { padding:10px; border-bottom:1px solid rgba(124,77,255,0.06); color:var(--text-secondary); word-break:break-all; }
        tr:hover td { background:var(--bg-card-hover); }
        tr:last-child td { border-bottom:none; }
        .ip-cell { font-family:'Courier New',monospace; color:var(--accent3); font-weight:600; cursor:pointer; }
        .ip-cell:hover { text-decoration:underline; }
        .flag-cell { font-size:16px; }
        .time-cell { white-space:nowrap; color:var(--text-muted); font-size:11px; }
        .ua-cell { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; }
        .map-link { color:var(--accent2); text-decoration:none; font-size:11px; }
        .map-link:hover { text-decoration:underline; }
        .detail-link { color:var(--accent); cursor:pointer; font-size:11px; }
        .detail-link:hover { text-decoration:underline; }
        .del-link { color:var(--danger); cursor:pointer; font-size:11px; margin-left:6px; }
        .del-link:hover { text-decoration:underline; }
        .pagination { display:flex; justify-content:center; align-items:center; gap:6px; padding:16px; color:var(--text-muted); font-size:13px; flex-wrap:wrap; }
        .pagination button { padding:5px 12px; border-radius:7px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-primary); cursor:pointer; font-size:12px; transition:all 0.2s; }
        .pagination button:hover { border-color:var(--accent); }
        .pagination button.active { background:var(--accent); border-color:var(--accent); color:white; }
        .pagination button:disabled { opacity:0.3; cursor:not-allowed; }
        .empty { text-align:center; padding:50px 20px; color:var(--text-muted); }
        .empty .emoji { font-size:44px; margin-bottom:10px; }
        .modal-overlay { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:200; display:flex; justify-content:center; align-items:center; }
        .modal-box { background:var(--bg-secondary); border:1px solid var(--border); border-radius:16px; padding:24px; max-width:600px; width:95%; max-height:90vh; overflow-y:auto; }
        .modal-box h3 { color:var(--accent3); margin-bottom:16px; font-size:18px; }
        .modal-close { float:right; background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer; }
        .modal-close:hover { color:var(--text-primary); }
        .modal-info { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        .modal-row { background:var(--bg-card); border-radius:8px; padding:10px 12px; }
        .modal-row .label { font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
        .modal-row .value { font-size:13px; color:var(--text-primary); word-break:break-all; }
        .modal-map { margin-top:14px; border-radius:10px; overflow:hidden; height:200px; }
        .modal-map iframe { width:100%; height:100%; border:none; filter:invert(0.9) hue-rotate(180deg) brightness(0.8) contrast(1.1); }
        .confirm-modal { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:300; display:flex; justify-content:center; align-items:center; }
        .confirm-box { background:var(--bg-secondary); border:1px solid var(--border); border-radius:14px; padding:28px; max-width:360px; width:90%; text-align:center; }
        .confirm-box h3 { margin-bottom:10px; color:var(--danger); }
        .confirm-box p { color:var(--text-secondary); font-size:13px; margin-bottom:20px; }
        .confirm-box .btns { display:flex; gap:10px; justify-content:center; }
        .confirm-box .btns button { padding:9px 22px; border-radius:8px; border:none; cursor:pointer; font-weight:600; font-size:13px; }
        @media (max-width:900px) { .viz-grid { grid-template-columns:1fr; } .modal-info { grid-template-columns:1fr; } }
        @media (max-width:600px) { .admin-wrap { padding:12px; } .stats-grid { grid-template-columns:repeat(2,1fr); } .modal-info { grid-template-columns:1fr; } table { font-size:10px; } th,td { padding:7px 5px; } .ua-cell { max-width:80px; } }
    </style>
</head>
<body>
<div class="login-wrap" id="loginPage">
    <div class="login-box">
        <h2>馃敀 绠＄悊鍚庡彴</h2>
        <p>IP浣嶇疆妫€娴嬪伐鍏?路 绠＄悊鍛樼櫥褰?/p>
        <input type="password" id="pwdInput" placeholder="璇疯緭鍏ョ鐞嗗憳瀵嗙爜" onkeydown="if(event.key==='Enter')doLogin()">
        <button onclick="doLogin()">鐧?褰?/button>
        <div class="login-error" id="loginError">瀵嗙爜閿欒锛岃閲嶈瘯</div>
    </div>
</div>
<div class="admin-wrap" id="adminPanel" style="display:none">
    <div class="admin-header">
        <h1>馃搳 璁块棶璁板綍 <span class="live-dot"></span></h1>
        <div class="actions">
            <button class="admin-btn btn-export" onclick="exportCSV()">馃摜 CSV</button>
            <button class="admin-btn btn-refresh" onclick="loadData()">馃攧</button>
            <button class="admin-btn btn-danger" onclick="showConfirm()">馃棏锔?/button>
            <button class="admin-btn btn-logout" onclick="doLogout()">馃毆</button>
        </div>
    </div>
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card"><div class="stat-value" id="sTotal">-</div><div class="stat-label">鎬昏闂?/div></div>
        <div class="stat-card"><div class="stat-value" id="sToday">-</div><div class="stat-label">浠婃棩</div></div>
        <div class="stat-card"><div class="stat-value" id="sUnique">-</div><div class="stat-label">鐙珛IP</div></div>
        <div class="stat-card"><div class="stat-value" id="sCountries">-</div><div class="stat-label">鍥藉</div></div>
        <div class="stat-card"><div class="stat-value" id="sRecent">-</div><div class="stat-label">杩?灏忔椂</div></div>
        <div class="stat-card"><div class="stat-value" id="sTopISP">-</div><div class="stat-label">TOP ISP</div></div>
    </div>
    <div class="viz-grid">
        <div class="viz-card"><h3>馃椇锔?璁块棶鑰呬綅缃?/h3><div id="adminMap"></div></div>
        <div class="viz-card"><h3>馃搱 7澶╄秼鍔?/h3><canvas id="trendChart"></canvas></div>
    </div>
    <div class="viz-grid">
        <div class="viz-card"><h3>馃實 鍥藉 TOP5</h3><canvas id="countryChart"></canvas></div>
        <div class="viz-card"><h3>馃寪 ISP TOP5</h3><canvas id="ispChart"></canvas></div>
    </div>
    <div class="toolbar">
        <input type="text" id="searchInput" placeholder="馃攳 鎼滅储IP/鍩庡競/ISP..." oninput="filterData()">
        <select id="countryFilter" onchange="filterData()"><option value="">鍏ㄩ儴鍥藉</option></select>
        <select id="ispFilter" onchange="filterData()"><option value="">鍏ㄩ儴ISP</option></select>
    </div>
    <div class="table-wrap">
        <table>
            <thead><tr>
                <th>#</th><th>IP鍦板潃</th><th>馃彸锔?/th><th>鍥藉</th><th>鍩庡競</th>
                <th>ISP</th><th>娴忚鍣?/th><th>鏃堕棿</th><th>鎿嶄綔</th>
            </tr></thead>
            <tbody id="tableBody"></tbody>
        </table>
    </div>
    <div class="pagination" id="pagination"></div>
</div>
<div class="modal-overlay" id="detailModal" style="display:none" onclick="if(event.target===this)closeDetail()">
    <div class="modal-box">
        <button class="modal-close" onclick="closeDetail()">脳</button>
        <h3 id="detailTitle">IP 璇︽儏</h3>
        <div class="modal-info" id="detailInfo"></div>
        <div class="modal-map" id="detailMap"></div>
    </div>
</div>
<div class="confirm-modal" id="confirmModal" style="display:none" onclick="if(event.target===this)closeConfirm()">
    <div class="confirm-box">
        <h3>鈿狅笍 纭娓呯┖</h3>
        <p>姝ゆ搷浣滃皢鍒犻櫎鎵€鏈夎闂褰曪紝涓嶅彲鎭㈠锛?/p>
        <div class="btns">
            <button style="background:var(--bg-card);color:var(--text-primary)" onclick="closeConfirm()">鍙栨秷</button>
            <button style="background:var(--danger);color:white" onclick="doClear()">纭娓呯┖</button>
        </div>
    </div>
</div>
<div class="confirm-modal" id="delConfirmModal" style="display:none" onclick="if(event.target===this)closeDelConfirm()">
    <div class="confirm-box">
        <h3>鈿狅笍 纭鍒犻櫎</h3>
        <p id="delConfirmText">纭鍒犻櫎杩欐潯璁板綍锛?/p>
        <div class="btns">
            <button style="background:var(--bg-card);color:var(--text-primary)" onclick="closeDelConfirm()">鍙栨秷</button>
            <button style="background:var(--danger);color:white" onclick="doDelete()">纭鍒犻櫎</button>
        </div>
    </div>
</div>
<script>
var allData=[], filteredData=[], currentPage=1, pageSize=30, cookieName='ip_detect_admin';
var adminMap=null, mapMarkers=[], trendChart=null, countryChart=null, ispChart=null, refreshTimer=null;
var pendingDeleteIndex = -1;

function getCookie(n){var m=document.cookie.match(new RegExp('(^| )'+n+'=([^;]+)'));return m?m[2]:'';}
function setCookie(n,v){document.cookie=n+'='+v+'; path=/; max-age=86400';}
function delCookie(n){document.cookie=n+'=; path=/; max-age=0';}
(function(){var t=getCookie(cookieName);if(t)showAdmin();})();

function doLogin(){
    var pwd=document.getElementById('pwdInput').value;
    fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})})
    .then(function(r){if(r.ok)return r.json();throw new Error();})
    .then(function(d){setCookie(cookieName,d.token);showAdmin();})
    .catch(function(){document.getElementById('loginError').style.display='block';setTimeout(function(){document.getElementById('loginError').style.display='none';},3000);});
}
function doLogout(){delCookie(cookieName);document.getElementById('adminPanel').style.display='none';document.getElementById('loginPage').style.display='flex';if(refreshTimer)clearInterval(refreshTimer);}

function showAdmin(){document.getElementById('loginPage').style.display='none';document.getElementById('adminPanel').style.display='block';initMap();loadData();if(refreshTimer)clearInterval(refreshTimer);refreshTimer=setInterval(loadData,30000);}

function initMap(){if(adminMap)return;adminMap=L.map('adminMap',{zoomControl:true}).setView([30,110],2);L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'漏OSM 漏CARTO',maxZoom:18}).addTo(adminMap);}

function loadData(){
    var token=getCookie(cookieName);
    fetch('/api/admin/visits',{headers:{'Authorization':'Bearer '+token}})
    .then(function(r){if(r.status===401){doLogout();return null;}return r.json();})
    .then(function(d){if(!d)return;allData=d.visits||[];allData.reverse();buildFilters();filterData();updateStats();updateMap();updateCharts();});
}

function updateStats(){
    document.getElementById('sTotal').textContent=allData.length;
    var today=new Date().toISOString().slice(0,10);
    var todayCount=allData.filter(function(v){return v.time&&v.time.startsWith(today)}).length;
    document.getElementById('sToday').textContent=todayCount;
    var ips={},countries={},isps={},now=Date.now(),recent1h=0;
    allData.forEach(function(v){ips[v.ip]=(ips[v.ip]||0)+1;if(v.country_code)countries[v.country_code]=1;if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=(isps[v.isp]||0)+1;if(v.time){var t=new Date(v.time.replace(/-/g,'/')).getTime();if(now-t<3600000)recent1h++;}});
    document.getElementById('sUnique').textContent=Object.keys(ips).length;
    document.getElementById('sCountries').textContent=Object.keys(countries).length;
    document.getElementById('sRecent').textContent=recent1h;
    var topISP=Object.entries(isps).sort(function(a,b){return b[1]-a[1]})[0];
    document.getElementById('sTopISP').textContent=topISP?(topISP[0].length>12?topISP[0].substring(0,11)+'..':topISP[0]):'-';
}

function buildFilters(){
    var cs={},isps={};
    allData.forEach(function(v){if(v.country)cs[v.country]=v.country_code||'';if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=1;});
    var cSel=document.getElementById('countryFilter');cSel.innerHTML='<option value="">鍏ㄩ儴鍥藉</option>';
    Object.keys(cs).sort().forEach(function(c){var o=document.createElement('option');o.value=cs[c];o.textContent=c;cSel.appendChild(o);});
    var iSel=document.getElementById('ispFilter');iSel.innerHTML='<option value="">鍏ㄩ儴ISP</option>';
    Object.keys(isps).sort().forEach(function(i){var o=document.createElement('option');o.value=i;o.textContent=i;iSel.appendChild(o);});
}

function codeToFlag(code){if(!code||code.length!==2)return '馃弫';var offset=127397;return String.fromCodePoint(code.charCodeAt(0)+offset)+String.fromCodePoint(code.charCodeAt(1)+offset);}

function filterData(){
    var q=document.getElementById('searchInput').value.toLowerCase();
    var cc=document.getElementById('countryFilter').value;
    var isp=document.getElementById('ispFilter').value;
    filteredData=allData.filter(function(v){
        var matchQ=!q||(v.ip&&v.ip.toLowerCase().indexOf(q)>-1)||(v.city&&v.city.toLowerCase().indexOf(q)>-1)||(v.isp&&v.isp.toLowerCase().indexOf(q)>-1)||(v.country&&v.country.toLowerCase().indexOf(q)>-1);
        return matchQ&&(!cc||v.country_code===cc)&&(!isp||v.isp===isp);
    });
    currentPage=1;renderTable();
}

function renderTable(){
    var tbody=document.getElementById('tableBody');
    var total=filteredData.length;
    var totalPages=Math.ceil(total/pageSize)||1;
    if(currentPage>totalPages)currentPage=totalPages;
    var start=(currentPage-1)*pageSize;
    var end=Math.min(start+pageSize,total);
    var pageData=filteredData.slice(start,end);
    if(pageData.length===0){tbody.innerHTML='<tr><td colspan="9"><div class="empty"><div class="emoji">馃摥</div>鏆傛棤璁板綍</div></td></tr>';}
    else{
        var html='';
        pageData.forEach(function(v,i){
            var idx=start+i+1;
            var ua=v.user_agent||'-';
            var shortUa=ua.length>35?(ua.indexOf('Chrome')>-1&&ua.indexOf('Edg')>-1?'Edge':ua.indexOf('Chrome')>-1?'Chrome':ua.indexOf('Firefox')>-1?'Firefox':ua.indexOf('Safari')>-1?'Safari':ua.substring(0,32)+'..'):ua;
            html+='<tr>';
            html+='<td>'+idx+'</td>';
            html+='<td class="ip-cell" onclick="showDetail(\\''+v.ip+'\\')">'+v.ip+'</td>';
            html+='<td class="flag-cell">'+codeToFlag(v.country_code)+'</td>';
            html+='<td>'+(v.country||'-')+'</td>';
            html+='<td>'+(v.city||'-')+(v.region&&v.region!=='鏈煡'?'<br><span style="font-size:10px;color:var(--text-muted)">'+v.region+'</span>':'')+'</td>';
            html+='<td style="font-size:11px">'+(v.isp||'-')+'</td>';
            html+='<td class="ua-cell" title="'+ua.replace(/"/g,'&quot;')+'">'+shortUa+'</td>';
            html+='<td class="time-cell">'+(v.time||'-')+'</td>';
            html+='<td><a class="map-link" href="https://www.google.com/maps?q='+(v.latitude||0)+','+(v.longitude||0)+'" target="_blank">馃搷</a> <span class="detail-link" onclick="showDetail(\\''+v.ip+'\\')">璇︽儏</span><span class="del-link" onclick="showDelConfirm('+i+')">鉁?/span></td>';
            html+='</tr>';
        });
        tbody.innerHTML=html;
    }
    var pagDiv=document.getElementById('pagination');
    if(totalPages<=1){pagDiv.innerHTML='<span>鍏?'+total+' 鏉?/span>';return;}
    var phtml='<button onclick="goPage('+(currentPage-1)+')" '+(currentPage===1?'disabled':'')+'>涓婁竴椤?/button>';
    var startP=Math.max(1,currentPage-4),endP=Math.min(totalPages,currentPage+4);
    for(var p=startP;p<=endP;p++)phtml+='<button class="'+(p===currentPage?'active':'')+'" onclick="goPage('+p+')">'+p+'</button>';
    phtml+='<button onclick="goPage('+(currentPage+1)+')" '+(currentPage===totalPages?'disabled':'')+'>涓嬩竴椤?/button>';
    phtml+='<span style="margin-left:10px">'+total+'鏉?/ '+totalPages+'椤?/span>';
    pagDiv.innerHTML=phtml;
}

function goPage(p){var totalPages=Math.ceil(filteredData.length/pageSize)||1;if(p<1||p>totalPages)return;currentPage=p;renderTable();}

function showDetail(ip){
    var v=allData.find(function(x){return x.ip===ip;});
    if(!v){alert('鏈壘鍒拌褰?);return;}
    document.getElementById('detailTitle').textContent='馃實 '+ip+' 璇︽儏';
    var html='',fields=[['IP鍦板潃',v.ip],['鍥藉',(v.country||'-')+' '+codeToFlag(v.country_code)],['鍩庡競',v.city||'-'],['鍦板尯',v.region||'-'],['缁忕含搴?,(v.latitude||'')+', '+(v.longitude||'')],['鏃跺尯',v.timezone||'-'],['ISP',v.isp||'-'],['AS缂栧彿',v.as||'-'],['閭紪',v.zip||'-'],['璁块棶鏃堕棿',v.time||'-']];
    fields.forEach(function(f){html+='<div class="modal-row"><div class="label">'+f[0]+'</div><div class="value">'+f[1]+'</div></div>';});
    document.getElementById('detailInfo').innerHTML=html;
    var lat=v.latitude||0,lon=v.longitude||0;
    var mapUrl='https://www.openstreetmap.org/export/embed.html?bbox='+(lon-0.05)+','+(lat-0.05)+','+(lon+0.05)+','+(lat+0.05)+'&layer=mapnik&marker='+lat+','+lon;
    document.getElementById('detailMap').innerHTML='<iframe src="'+mapUrl+'" loading="lazy"></iframe>';
    document.getElementById('detailModal').style.display='flex';
}
function closeDetail(){document.getElementById('detailModal').style.display='none';}

function showDelConfirm(idx){pendingDeleteIndex=idx;var v=filteredData[idx];document.getElementById('delConfirmText').textContent='纭鍒犻櫎 '+v.ip+' 鐨勮褰曪紵';document.getElementById('delConfirmModal').style.display='flex';}
function closeDelConfirm(){document.getElementById('delConfirmModal').style.display='none';pendingDeleteIndex=-1;}
function doDelete(){
    if(pendingDeleteIndex<0)return;
    var v=filteredData[pendingDeleteIndex];
    var token=getCookie(cookieName);
    fetch('/api/admin/visits/'+encodeURIComponent(v.ip),{method:'DELETE',headers:{'Authorization':'Bearer '+token}})
    .then(function(r){if(r.status===401){doLogout();return;}closeDelConfirm();loadData();});
}

function updateMap(){
    if(!adminMap)return;mapMarkers.forEach(function(m){adminMap.removeLayer(m);});mapMarkers=[];
    var seen={};allData.forEach(function(v){if(seen[v.ip])return;seen[v.ip]=1;var lat=parseFloat(v.latitude),lon=parseFloat(v.longitude);if(isNaN(lat)||isNaN(lon))return;var flag=codeToFlag(v.country_code);var popup='<b>'+flag+' '+(v.city||'鏈煡')+'</b><br>IP: '+v.ip+'<br>ISP: '+(v.isp||'鏈煡')+'<br>'+(v.time||'');var marker=L.circleMarker([lat,lon],{radius:5,fillColor:'#7c4dff',color:'#448aff',weight:1,opacity:0.8,fillOpacity:0.6}).addTo(adminMap).bindPopup(popup);mapMarkers.push(marker);});
    if(mapMarkers.length>0)adminMap.fitBounds(mapMarkers.map(function(m){return m.getLatLng()}),{padding:[30,30],maxZoom:6});
}

function updateCharts(){
    var days={};for(var i=6;i>=0;i--){var d=new Date(Date.now()-i*86400000);days[d.toISOString().slice(0,10)]=0;}
    allData.forEach(function(v){if(v.time){var d=v.time.substring(0,10);if(d in days)days[d]++;}});
    var labels=Object.keys(days).map(function(d){return d.substring(5);}),values=Object.values(days);
    var ctx1=document.getElementById('trendChart').getContext('2d');
    if(trendChart)trendChart.destroy();
    trendChart=new Chart(ctx1,{type:'line',data:{labels:labels,datasets:[{label:'璁块棶閲?,data:values,borderColor:'#7c4dff',backgroundColor:'rgba(124,77,255,0.1)',fill:true,tension:0.4,pointBackgroundColor:'#18ffff',pointRadius:4}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#5c6bc0'},grid:{color:'rgba(124,77,255,0.08)'}},y:{ticks:{color:'#5c6bc0',stepSize:1},grid:{color:'rgba(124,77,255,0.08)'},beginAtZero:true}}}});
    var ccs={};allData.forEach(function(v){if(v.country&&v.country!=='鏈煡')ccs[v.country]=(ccs[v.country]||0)+1;});
    var cSorted=Object.entries(ccs).sort(function(a,b){return b[1]-a[1]}).slice(0,5);
    var ctx2=document.getElementById('countryChart').getContext('2d');
    if(countryChart)countryChart.destroy();
    countryChart=new Chart(ctx2,{type:'doughnut',data:{labels:cSorted.map(function(x){return x[0]}),datasets:[{data:cSorted.map(function(x){return x[1]}),backgroundColor:['#7c4dff','#448aff','#18ffff','#69f0ae','#ffd740'],borderColor:'#111640',borderWidth:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{color:'#9fa8da',font:{size:11}}}}}});
    var isps={};allData.forEach(function(v){if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=(isps[v.isp]||0)+1;});
    var iSorted=Object.entries(isps).sort(function(a,b){return b[1]-a[1]}).slice(0,5);
    var ctx3=document.getElementById('ispChart').getContext('2d');
    if(ispChart)ispChart.destroy();
    ispChart=new Chart(ctx3,{type:'doughnut',data:{labels:iSorted.map(function(x){return x[0].length>18?x[0].substring(0,16)+'..':x[0]}),datasets:[{data:iSorted.map(function(x){return x[1]}),backgroundColor:['#ff5252','#ff9100','#ffd740','#69f0ae','#18ffff'],borderColor:'#111640',borderWidth:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{color:'#9fa8da',font:{size:11}}}}}});
}

function exportCSV(){
    var token=getCookie(cookieName);
    fetch('/api/admin/visits',{headers:{'Authorization':'Bearer '+token}})
    .then(function(r){return r.json();}).then(function(d){
        var visits=d.visits||[];if(!visits.length){alert('鏃犺褰?);return;}
        var csv='\uFEFFIP,鍥藉,鍥藉浠ｇ爜,鍩庡競,鍦板尯,绾害,缁忓害,鏃跺尯,ISP,AS,UA,鏉ユ簮,鏃堕棿\n';
        visits.forEach(function(v){csv+=[v.ip,v.country,v.country_code,v.city,v.region,v.latitude,v.longitude,v.timezone,v.isp,v.as||'','"'+(v.user_agent||'').replace(/"/g,'""')+'"',v.referer||'',v.time].join(',')+'\n';});
        var blob=new Blob([csv],{type:'text/csv;charset=utf-8'});var url=URL.createObjectURL(blob);var a=document.createElement('a');a.href=url;a.download='ip_visits_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(url);
    });
}
function showConfirm(){document.getElementById('confirmModal').style.display='flex';}
function closeConfirm(){document.getElementById('confirmModal').style.display='none';}
function doClear(){var token=getCookie(cookieName);fetch('/api/admin/clear',{method:'POST',headers:{'Authorization':'Bearer '+token}}).then(function(r){if(r.status===401){doLogout();return;}closeConfirm();loadData();});}
</script>
</body>
</html>"""


# ========== 璺敱 ==========

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
        ("__COUNTRY__", location.get("country", "鏈煡")),
        ("__COUNTRY_CODE__", location.get("country_code", "鏈煡")),
        ("__CITY__", location.get("city", "鏈煡")),
        ("__REGION__", location.get("region_name", "鏈煡")),
        ("__REGION_NAME__", location.get("region_name", "鏈煡")),
        ("__LAT__", str(lat)), ("__LON__", str(lon)),
        ("__TIMEZONE__", location.get("timezone", "鏈煡")),
        ("__ISP__", location.get("isp", "鏈煡")),
        ("__AS__", location.get("as", "鏈煡")),
        ("__ZIP__", location.get("zip", "鏈煡")),
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
        return {"error": "IP鏍煎紡閿欒", "ip": ip, "location": None}
    try:
        for p in parts:
            if not 0 <= int(p) <= 255:
                return {"error": "IP鏍煎紡閿欒", "ip": ip, "location": None}
    except ValueError:
        return {"error": "IP鏍煎紡閿欒", "ip": ip, "location": None}
    location = await _fetch_location(ip)
    if not location:
        return {"error": "鏌ヨ澶辫触", "ip": ip, "location": None}
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
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ========== 绠＄悊鍛楢PI ==========

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
        raise HTTPException(status_code=401, detail="瀵嗙爜閿欒")
    token = base64.b64encode(pwd.encode("utf-8")).decode("utf-8")
    return {"token": token, "message": "鐧诲綍鎴愬姛"}


@app.get("/api/admin/visits")
async def admin_get_visits(request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="鏈巿鏉?)
    visits = _load_visits()
    return {"visits": visits, "total": len(visits)}


@app.delete("/api/admin/visits/{ip}")
async def admin_delete_visit(ip: str, request: Request):
    """鍒犻櫎鎸囧畾IP鐨勮闂褰曪紙鍒犻櫎鏈€杩戜竴鏉★級"""
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="鏈巿鏉?)
    visits = _load_visits()
    for i in range(len(visits)-1, -1, -1):
        if visits[i].get("ip") == ip:
            visits.pop(i)
            _save_visits(visits, force=True)
            return {"message": "宸插垹闄?, "ip": ip}
    raise HTTPException(status_code=404, detail="鏈壘鍒拌褰?)


@app.post("/api/admin/clear")
async def admin_clear_visits(request: Request):
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="鏈巿鏉?)
    _save_visits([], force=True)
    return {"message": "宸叉竻绌?}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(content=ADMIN_HTML)


@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name": "IP浣嶇疆妫€娴?, "short_name": "IP瀹氫綅", "start_url": "/",
        "display": "standalone", "background_color": "#0a0e27", "theme_color": "#7c4dff",
        "icons": [{"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>馃實</text></svg>", "sizes": "any", "type": "image/svg+xml"}]
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
