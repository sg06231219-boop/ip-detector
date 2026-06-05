from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
import os
import json
from datetime import datetime
from typing import Optional

app = FastAPI()

# ========== 数据存储 ==========
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VISITS_FILE = os.path.join(DATA_DIR, "visits.json")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Lys13579")

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def _load_visits() -> list:
    _ensure_data_dir()
    if os.path.exists(VISITS_FILE):
        try:
            with open(VISITS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def _save_visits(visits: list):
    _ensure_data_dir()
    # 只保留最近2000条
    if len(visits) > 2000:
        visits = visits[-2000:]
    with open(VISITS_FILE, "w", encoding="utf-8") as f:
        json.dump(visits, f, ensure_ascii=False, indent=2)

def _record_visit(ip: str, location: dict, user_agent: str = "", referer: str = ""):
    """记录一次访问"""
    visits = _load_visits()
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
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    visits.append(visit)
    _save_visits(visits)
    return visit

def _get_client_ip(request: Request) -> str:
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        return ip.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

async def _fetch_location(ip: str) -> dict:
    """查询IP地理位置"""
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
                    return {
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
    <meta name="description" content="一键检测您的IP地址、地理位置、ISP信息、浏览器指纹">
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
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        #particles {
            position: fixed; top:0; left:0; width:100%; height:100%;
            z-index: 0; pointer-events: none;
        }
        .wrapper {
            position: relative; z-index: 1;
            max-width: 900px; margin: 0 auto; padding: 30px 20px;
        }
        .header {
            text-align: center; padding: 40px 0 30px;
            animation: fadeInDown 0.6s ease-out;
        }
        .header h1 {
            font-size: 42px; font-weight: 800;
            background: linear-gradient(135deg, var(--accent), var(--accent2), var(--accent3));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text; margin-bottom: 8px;
        }
        .header p { color: var(--text-secondary); font-size: 15px; }
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
        .ip-hero {
            text-align: center; margin: 30px 0;
            animation: fadeInUp 0.6s ease-out 0.2s both;
        }
        .ip-hero .ip-label { color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 8px; }
        .ip-hero .ip-value {
            font-size: clamp(28px, 6vw, 48px); font-weight: 800;
            font-family: 'Courier New', monospace;
            background: linear-gradient(90deg, var(--accent3), var(--accent2));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text; cursor: pointer; position: relative;
            transition: filter 0.2s;
        }
        .ip-hero .ip-value:hover { filter: brightness(1.3); }
        .ip-hero .copy-hint {
            font-size: 11px; color: var(--text-muted); margin-top: 6px;
            opacity: 0.6; transition: opacity 0.3s;
        }
        .ip-hero .ip-value:hover + .copy-hint { opacity: 1; }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px; margin: 30px 0;
        }
        .info-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 16px; padding: 20px;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
            animation: fadeInUp 0.5s ease-out both;
        }
        .info-card:hover {
            background: var(--bg-card-hover);
            border-color: rgba(124,77,255,0.4);
            transform: translateY(-2px);
            box-shadow: 0 8px 32px rgba(124,77,255,0.15);
        }
        .info-card .card-header {
            display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
        }
        .info-card .card-icon {
            width: 36px; height: 36px; border-radius: 10px;
            display: flex; align-items: center; justify-content: center;
            font-size: 18px; flex-shrink: 0;
        }
        .info-card .card-title {
            font-size: 13px; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 1px;
        }
        .info-card .card-value {
            font-size: 20px; font-weight: 700; color: var(--text-primary);
            word-break: break-all;
        }
        .info-card .card-sub {
            font-size: 12px; color: var(--text-secondary); margin-top: 4px;
        }
        .card-location .card-icon { background: rgba(124,77,255,0.15); }
        .card-city .card-icon { background: rgba(68,138,255,0.15); }
        .card-coords .card-icon { background: rgba(24,255,255,0.15); }
        .card-timezone .card-icon { background: rgba(255,214,0,0.15); }
        .card-isp .card-icon { background: rgba(105,240,174,0.15); }
        .card-as .card-icon { background: rgba(255,145,0,0.15); }
        .card-region .card-icon { background: rgba(255,82,82,0.15); }
        .card-browser .card-icon { background: rgba(234,128,252,0.15); }
        .map-section { margin: 30px 0; animation: fadeInUp 0.6s ease-out 0.8s both; }
        .map-section h3 {
            font-size: 16px; color: var(--text-secondary); margin-bottom: 12px;
            display: flex; align-items: center; gap: 8px;
        }
        .map-container {
            border-radius: 16px; overflow: hidden;
            border: 1px solid var(--border);
            height: 300px; background: var(--bg-secondary);
        }
        .map-container iframe { width: 100%; height: 100%; border: none; filter: invert(0.9) hue-rotate(180deg) brightness(0.9) contrast(1.1); }
        .actions {
            display: flex; gap: 12px; flex-wrap: wrap;
            margin: 24px 0; animation: fadeInUp 0.6s ease-out 1s both;
        }
        .btn {
            flex: 1; min-width: 140px; padding: 14px 20px;
            border-radius: 12px; border: none; cursor: pointer;
            font-size: 14px; font-weight: 600;
            display: flex; align-items: center; justify-content: center; gap: 8px;
            transition: all 0.3s; text-decoration: none;
        }
        .btn-primary {
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: white;
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,77,255,0.3); }
        .btn-secondary {
            background: var(--bg-card); color: var(--text-primary);
            border: 1px solid var(--border);
        }
        .btn-secondary:hover { background: var(--bg-card-hover); border-color: var(--accent); }
        .btn-success {
            background: rgba(105,240,174,0.15); color: var(--success);
            border: 1px solid rgba(105,240,174,0.3);
        }
        .btn-success:hover { background: rgba(105,240,174,0.25); }
        .toast {
            position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(100px);
            background: var(--bg-secondary); border: 1px solid var(--accent);
            color: var(--text-primary); padding: 12px 24px; border-radius: 12px;
            font-size: 14px; z-index: 1000;
            transition: transform 0.3s ease; pointer-events: none;
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
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 12px; padding: 16px; margin-top: 8px;
            font-family: 'Courier New', monospace; font-size: 12px;
            color: var(--accent3); overflow-x: auto;
            max-height: 0; overflow: hidden; transition: max-height 0.3s ease, padding 0.3s;
            padding: 0 16px;
        }
        .json-content.show { max-height: 600px; padding: 16px; }
        .footer {
            text-align: center; padding: 30px 0 20px;
            color: var(--text-muted); font-size: 12px;
            border-top: 1px solid var(--border); margin-top: 40px;
        }
        .footer a { color: var(--accent2); text-decoration: none; }
        @keyframes fadeInUp {
            from { opacity:0; transform:translateY(20px); }
            to { opacity:1; transform:translateY(0); }
        }
        @keyframes fadeInDown {
            from { opacity:0; transform:translateY(-20px); }
            to { opacity:1; transform:translateY(0); }
        }
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
        }
    </style>
</head>
<body>
    <canvas id="particles"></canvas>
    <div class="wrapper">
        <div class="header">
            <h1>🌍 IP 智能定位</h1>
            <p>实时检测您的网络身份与地理位置</p>
            <div class="status-badge">
                <span class="status-dot"></span>
                检测完成 · __TIMESTAMP__
            </div>
        </div>
        <div class="ip-hero">
            <div class="ip-label">您的公网 IP 地址</div>
            <div class="ip-value" onclick="copyIP()" title="点击复制">__IP__</div>
            <div class="copy-hint">点击IP即可复制</div>
        </div>
        <div class="info-grid" id="infoGrid">
            <div class="info-card card-location">
                <div class="card-header">
                    <div class="card-icon">🏳️</div>
                    <div class="card-title">国家/地区</div>
                </div>
                <div class="card-value">__COUNTRY_FLAG__ __COUNTRY__</div>
                <div class="card-sub">代码: __COUNTRY_CODE__</div>
            </div>
            <div class="info-card card-city">
                <div class="card-header">
                    <div class="card-icon">🏙️</div>
                    <div class="card-title">城市</div>
                </div>
                <div class="card-value">__CITY__</div>
                <div class="card-sub">地区: __REGION__</div>
            </div>
            <div class="info-card card-coords">
                <div class="card-header">
                    <div class="card-icon">🗺️</div>
                    <div class="card-title">经纬度</div>
                </div>
                <div class="card-value">__LAT__, __LON__</div>
                <div class="card-sub">WGS84坐标系</div>
            </div>
            <div class="info-card card-timezone">
                <div class="card-header">
                    <div class="card-icon">⏰</div>
                    <div class="card-title">时区</div>
                </div>
                <div class="card-value">__TIMEZONE__</div>
                <div class="card-sub" id="localTime">本地时间: 加载中...</div>
            </div>
            <div class="info-card card-isp">
                <div class="card-header">
                    <div class="card-icon">🌐</div>
                    <div class="card-title">ISP 运营商</div>
                </div>
                <div class="card-value">__ISP__</div>
                <div class="card-sub">互联网服务提供商</div>
            </div>
            <div class="info-card card-as">
                <div class="card-header">
                    <div class="card-icon">🔗</div>
                    <div class="card-title">AS 编号</div>
                </div>
                <div class="card-value" style="font-size:16px;">__AS__</div>
                <div class="card-sub">自治系统编号</div>
            </div>
            <div class="info-card card-region">
                <div class="card-header">
                    <div class="card-icon">📍</div>
                    <div class="card-title">精确区域</div>
                </div>
                <div class="card-value" style="font-size:16px;">__REGION_NAME__</div>
                <div class="card-sub">邮编: __ZIP__</div>
            </div>
            <div class="info-card card-browser">
                <div class="card-header">
                    <div class="card-icon">🖥️</div>
                    <div class="card-title">您的浏览器</div>
                </div>
                <div class="card-value" style="font-size:14px;" id="browserInfo">检测中...</div>
                <div class="card-sub" id="screenInfo"></div>
            </div>
        </div>
        <div class="map-section">
            <h3>📍 地理位置可视化</h3>
            <div class="map-container">
                <iframe src="https://www.openstreetmap.org/export/embed.html?bbox=__MAP_BBOX__&layer=mapnik&marker=__LAT__,__LON__" loading="lazy"></iframe>
            </div>
        </div>
        <div class="actions">
            <a href="https://www.google.com/maps?q=__LAT__,__LON__" target="_blank" class="btn btn-primary">
                🗺️ Google地图查看
            </a>
            <button class="btn btn-secondary" onclick="copyAll()">
                📋 复制全部信息
            </button>
            <button class="btn btn-success" onclick="copyIP()">
                📌 复制IP地址
            </button>
        </div>
        <div class="json-section">
            <button class="json-toggle" onclick="toggleJSON(this)">
                <span class="arrow">▶</span> 查看 JSON 原始数据
            </button>
            <div class="json-content" id="jsonContent">__JSON_DATA__</div>
        </div>
        <div class="footer">
            IP智能定位工具 · 数据来源 ip-api.com · 检测时间 __TIMESTAMP__<br>
            <span style="opacity:0.5;">位置为大致估算，不代表精确住址</span>
        </div>
    </div>
    <div class="toast" id="toast"></div>
    <script>
    (function(){
        var c=document.getElementById('particles'),ctx=c.getContext('2d'),ps=[];
        function resize(){c.width=window.innerWidth;c.height=window.innerHeight}
        resize();window.addEventListener('resize',resize);
        for(var i=0;i<60;i++)ps.push({x:Math.random()*c.width,y:Math.random()*c.height,vx:(Math.random()-0.5)*0.3,vy:(Math.random()-0.5)*0.3,r:Math.random()*1.5+0.5,o:Math.random()*0.4+0.1});
        function draw(){ctx.clearRect(0,0,c.width,c.height);for(var i=0;i<ps.length;i++){var p=ps[i];p.x+=p.vx;p.y+=p.vy;if(p.x<0)p.x=c.width;if(p.x>c.width)p.x=0;if(p.y<0)p.y=c.height;if(p.y>c.height)p.y=0;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fillStyle='rgba(124,77,255,'+p.o+')';ctx.fill();for(var j=i+1;j<ps.length;j++){var q=ps[j],dx=p.x-q.x,dy=p.y-q.y,d=Math.sqrt(dx*dx+dy*dy);if(d<120){ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.strokeStyle='rgba(124,77,255,'+(0.08*(1-d/120))+')';ctx.stroke()}}}requestAnimationFrame(draw)}
        draw();
    })();
    (function(){
        var ua=navigator.userAgent,b='未知';
        if(ua.indexOf('Edg')>-1)b='Microsoft Edge';
        else if(ua.indexOf('Chrome')>-1)b='Google Chrome';
        else if(ua.indexOf('Firefox')>-1)b='Mozilla Firefox';
        else if(ua.indexOf('Safari')>-1)b='Apple Safari';
        else if(ua.indexOf('Opera')>-1)b='Opera';
        document.getElementById('browserInfo').textContent=b;
        document.getElementById('screenInfo').textContent=screen.width+'x'+screen.height+' · '+(navigator.language||'未知');
    })();
    (function(){
        try{var tz='__TIMEZONE__';if(tz&&tz!=='未知'){var now=new Date();var opts={timeZone:tz,hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'};document.getElementById('localTime').textContent='本地时间: '+now.toLocaleString('zh-CN',opts)}}catch(e){}
    })();
    function copyIP(){navigator.clipboard.writeText('__IP__').then(function(){showToast('✅ IP地址已复制')})}
    function copyAll(){
        var data=__JSON_RAW__,t='IP地址: '+data.ip+'\\n';
        if(data.location){var l=data.location;t+='国家: '+l.country+' ('+l.country_code+')\\n';t+='城市: '+l.city+'\\n';t+='地区: '+(l.region_name||'未知')+'\\n';t+='经纬度: '+l.latitude+', '+l.longitude+'\\n';t+='时区: '+l.timezone+'\\n';t+='ISP: '+l.isp+'\\n';t+='AS: '+(l.as||'未知')+'\\n'}
        navigator.clipboard.writeText(t).then(function(){showToast('✅ 全部信息已复制')})
    }
    function showToast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}
    function toggleJSON(b){b.classList.toggle('open');document.getElementById('jsonContent').classList.toggle('show')}
    </script>
</body>
</html>"""


# ========== 管理员后台模板 ==========
ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理后台 - IP位置检测</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🔒</text></svg>">
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
            --warning: #ffd740;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary); color: var(--text-primary);
            min-height: 100vh;
        }
        .login-wrap {
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 20px;
        }
        .login-box {
            background: var(--bg-secondary); border: 1px solid var(--border);
            border-radius: 20px; padding: 40px; max-width: 400px; width: 100%;
            text-align: center;
        }
        .login-box h2 { color: var(--accent3); margin-bottom: 8px; font-size: 24px; }
        .login-box p { color: var(--text-muted); font-size: 13px; margin-bottom: 24px; }
        .login-box input {
            width: 100%; padding: 14px 16px; border-radius: 12px;
            border: 1px solid var(--border); background: var(--bg-card);
            color: var(--text-primary); font-size: 15px; margin-bottom: 16px;
            outline: none; transition: border-color 0.3s;
        }
        .login-box input:focus { border-color: var(--accent); }
        .login-box button {
            width: 100%; padding: 14px; border-radius: 12px; border: none;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: white; font-size: 15px; font-weight: 600; cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .login-box button:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,77,255,0.3); }
        .login-error { color: var(--danger); font-size: 13px; margin-top: 12px; display: none; }
        /* 管理面板 */
        .admin-wrap { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .admin-header {
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px 0; border-bottom: 1px solid var(--border); margin-bottom: 24px;
        }
        .admin-header h1 {
            font-size: 24px;
            background: linear-gradient(135deg, var(--accent), var(--accent3));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .admin-header .actions { display: flex; gap: 10px; }
        .admin-btn {
            padding: 8px 16px; border-radius: 8px; border: none; cursor: pointer;
            font-size: 13px; font-weight: 600; transition: all 0.2s;
        }
        .btn-logout { background: rgba(255,82,82,0.15); color: var(--danger); border: 1px solid rgba(255,82,82,0.3); }
        .btn-logout:hover { background: rgba(255,82,82,0.3); }
        .btn-refresh { background: rgba(105,240,174,0.15); color: var(--success); border: 1px solid rgba(105,240,174,0.3); }
        .btn-refresh:hover { background: rgba(105,240,174,0.3); }
        .btn-danger { background: rgba(255,82,82,0.15); color: var(--danger); border: 1px solid rgba(255,82,82,0.3); }
        .btn-danger:hover { background: rgba(255,82,82,0.3); }
        /* 统计卡片 */
        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px; margin-bottom: 24px;
        }
        .stat-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 16px; padding: 20px; text-align: center;
        }
        .stat-card .stat-value {
            font-size: 32px; font-weight: 800;
            background: linear-gradient(135deg, var(--accent3), var(--accent2));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        }
        .stat-card .stat-label { color: var(--text-muted); font-size: 13px; margin-top: 4px; }
        /* 搜索/过滤 */
        .toolbar {
            display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
        }
        .toolbar input, .toolbar select {
            padding: 10px 14px; border-radius: 10px;
            border: 1px solid var(--border); background: var(--bg-card);
            color: var(--text-primary); font-size: 13px; outline: none;
        }
        .toolbar input:focus, .toolbar select:focus { border-color: var(--accent); }
        .toolbar input { flex: 1; min-width: 200px; }
        /* 表格 */
        .table-wrap {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 16px; overflow: hidden;
        }
        table {
            width: 100%; border-collapse: collapse; font-size: 13px;
        }
        thead { background: rgba(124,77,255,0.1); }
        th {
            padding: 14px 12px; text-align: left; color: var(--text-muted);
            font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
            border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        td {
            padding: 12px; border-bottom: 1px solid rgba(124,77,255,0.08);
            color: var(--text-secondary); word-break: break-all;
        }
        tr:hover td { background: var(--bg-card-hover); }
        .ip-cell {
            font-family: 'Courier New', monospace; color: var(--accent3);
            font-weight: 600; cursor: pointer;
        }
        .ip-cell:hover { text-decoration: underline; }
        .flag-cell { font-size: 18px; }
        .time-cell { white-space: nowrap; color: var(--text-muted); font-size: 12px; }
        .ua-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .map-link {
            color: var(--accent2); text-decoration: none; font-size: 12px;
        }
        .map-link:hover { text-decoration: underline; }
        /* 分页 */
        .pagination {
            display: flex; justify-content: center; align-items: center;
            gap: 8px; padding: 20px; color: var(--text-muted); font-size: 13px;
        }
        .pagination button {
            padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border);
            background: var(--bg-card); color: var(--text-primary); cursor: pointer;
            font-size: 13px; transition: all 0.2s;
        }
        .pagination button:hover { border-color: var(--accent); }
        .pagination button.active {
            background: var(--accent); border-color: var(--accent); color: white;
        }
        .pagination button:disabled { opacity: 0.3; cursor: not-allowed; }
        /* 空状态 */
        .empty { text-align: center; padding: 60px 20px; color: var(--text-muted); }
        .empty .emoji { font-size: 48px; margin-bottom: 12px; }
        /* 确认弹窗 */
        .modal-overlay {
            position: fixed; top:0; left:0; width:100%; height:100%;
            background: rgba(0,0,0,0.6); z-index: 100;
            display: flex; justify-content: center; align-items: center;
        }
        .modal-box {
            background: var(--bg-secondary); border: 1px solid var(--border);
            border-radius: 16px; padding: 30px; max-width: 400px; width: 90%;
            text-align: center;
        }
        .modal-box h3 { margin-bottom: 12px; color: var(--danger); }
        .modal-box p { color: var(--text-secondary); font-size: 14px; margin-bottom: 20px; }
        .modal-box .modal-actions { display: flex; gap: 10px; justify-content: center; }
        .modal-box .modal-actions button { padding: 10px 24px; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; }
        @media (max-width: 768px) {
            .admin-wrap { padding: 12px; }
            .admin-header { flex-direction: column; gap: 12px; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            table { font-size: 11px; }
            th, td { padding: 8px 6px; }
            .ua-cell { max-width: 100px; }
        }
    </style>
</head>
<body>
<!-- 登录页 -->
<div class="login-wrap" id="loginPage">
    <div class="login-box">
        <h2>🔒 管理后台</h2>
        <p>IP位置检测工具 · 管理员登录</p>
        <input type="password" id="pwdInput" placeholder="请输入管理员密码" onkeydown="if(event.key==='Enter')doLogin()">
        <button onclick="doLogin()">登 录</button>
        <div class="login-error" id="loginError">密码错误，请重试</div>
    </div>
</div>

<!-- 管理面板 -->
<div class="admin-wrap" id="adminPanel" style="display:none">
    <div class="admin-header">
        <h1>📊 访问记录管理</h1>
        <div class="actions">
            <button class="admin-btn btn-refresh" onclick="loadData()">🔄 刷新</button>
            <button class="admin-btn btn-danger" onclick="confirmClear()">🗑️ 清空记录</button>
            <button class="admin-btn btn-logout" onclick="doLogout()">🚪 退出</button>
        </div>
    </div>

    <div class="stats-grid" id="statsGrid">
        <div class="stat-card"><div class="stat-value" id="statTotal">-</div><div class="stat-label">总访问量</div></div>
        <div class="stat-card"><div class="stat-value" id="statToday">-</div><div class="stat-label">今日访问</div></div>
        <div class="stat-card"><div class="stat-value" id="statUnique">-</div><div class="stat-label">独立IP数</div></div>
        <div class="stat-card"><div class="stat-value" id="statCountries">-</div><div class="stat-label">国家/地区</div></div>
    </div>

    <div class="toolbar">
        <input type="text" id="searchInput" placeholder="🔍 搜索IP、城市、ISP..." oninput="filterData()">
        <select id="countryFilter" onchange="filterData()">
            <option value="">全部国家</option>
        </select>
    </div>

    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>IP地址</th>
                    <th>🏳️</th>
                    <th>国家</th>
                    <th>城市</th>
                    <th>ISP</th>
                    <th>浏览器UA</th>
                    <th>访问时间</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody id="tableBody"></tbody>
        </table>
    </div>

    <div class="pagination" id="pagination"></div>
</div>

<!-- 确认弹窗 -->
<div class="modal-overlay" id="clearModal" style="display:none">
    <div class="modal-box">
        <h3>⚠️ 确认清空</h3>
        <p>此操作将删除所有访问记录，不可恢复！</p>
        <div class="modal-actions">
            <button style="background:var(--bg-card);color:var(--text-primary)" onclick="closeModal()">取消</button>
            <button style="background:var(--danger);color:white" onclick="doClear()">确认清空</button>
        </div>
    </div>
</div>

<script>
var allData = [];
var filteredData = [];
var currentPage = 1;
var pageSize = 50;
var cookieName = 'ip_detect_admin';

function getCookie(n) {
    var m = document.cookie.match(new RegExp('(^| )' + n + '=([^;]+)'));
    return m ? m[2] : '';
}
function setCookie(n, v) {
    document.cookie = n + '=' + v + '; path=/; max-age=86400';
}
function delCookie(n) {
    document.cookie = n + '=; path=/; max-age=0';
}

// 自动检测登录状态
(function() {
    var token = getCookie(cookieName);
    if (token) {
        showAdmin();
    }
})();

function doLogin() {
    var pwd = document.getElementById('pwdInput').value;
    fetch('/api/admin/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: pwd})
    }).then(function(r) {
        if (r.ok) return r.json();
        throw new Error('fail');
    }).then(function(d) {
        setCookie(cookieName, d.token);
        showAdmin();
    }).catch(function() {
        document.getElementById('loginError').style.display = 'block';
        setTimeout(function(){ document.getElementById('loginError').style.display='none'; }, 3000);
    });
}

function doLogout() {
    delCookie(cookieName);
    document.getElementById('adminPanel').style.display = 'none';
    document.getElementById('loginPage').style.display = 'flex';
    document.getElementById('pwdInput').value = '';
}

function showAdmin() {
    document.getElementById('loginPage').style.display = 'none';
    document.getElementById('adminPanel').style.display = 'block';
    loadData();
}

function loadData() {
    var token = getCookie(cookieName);
    fetch('/api/admin/visits', {
        headers: {'Authorization': 'Bearer ' + token}
    }).then(function(r) {
        if (r.status === 401) { doLogout(); return null; }
        return r.json();
    }).then(function(d) {
        if (!d) return;
        allData = d.visits || [];
        allData.reverse(); // 最新的在前
        buildCountryFilter();
        filterData();
        updateStats();
    });
}

function updateStats() {
    document.getElementById('statTotal').textContent = allData.length;
    var today = new Date().toISOString().slice(0, 10);
    var todayCount = allData.filter(function(v) { return v.time && v.time.startsWith(today); }).length;
    document.getElementById('statToday').textContent = todayCount;
    var ips = {};
    var countries = {};
    allData.forEach(function(v) {
        ips[v.ip] = 1;
        if (v.country_code) countries[v.country_code] = 1;
    });
    document.getElementById('statUnique').textContent = Object.keys(ips).length;
    document.getElementById('statCountries').textContent = Object.keys(countries).length;
}

function buildCountryFilter() {
    var cs = {};
    allData.forEach(function(v) { if (v.country) cs[v.country] = v.country_code || ''; });
    var sel = document.getElementById('countryFilter');
    sel.innerHTML = '<option value="">全部国家</option>';
    Object.keys(cs).sort().forEach(function(c) {
        var opt = document.createElement('option');
        opt.value = cs[c];
        opt.textContent = c;
        sel.appendChild(opt);
    });
}

function codeToFlag(code) {
    if (!code || code.length !== 2) return '🏁';
    var offset = 127397;
    return String.fromCodePoint(code.charCodeAt(0) + offset) + String.fromCodePoint(code.charCodeAt(1) + offset);
}

function filterData() {
    var q = document.getElementById('searchInput').value.toLowerCase();
    var cc = document.getElementById('countryFilter').value;
    filteredData = allData.filter(function(v) {
        var matchQ = !q || (v.ip && v.ip.toLowerCase().indexOf(q) > -1) ||
            (v.city && v.city.toLowerCase().indexOf(q) > -1) ||
            (v.isp && v.isp.toLowerCase().indexOf(q) > -1) ||
            (v.country && v.country.toLowerCase().indexOf(q) > -1);
        var matchCC = !cc || v.country_code === cc;
        return matchQ && matchCC;
    });
    currentPage = 1;
    renderTable();
}

function renderTable() {
    var tbody = document.getElementById('tableBody');
    var total = filteredData.length;
    var totalPages = Math.ceil(total / pageSize) || 1;
    if (currentPage > totalPages) currentPage = totalPages;
    var start = (currentPage - 1) * pageSize;
    var end = Math.min(start + pageSize, total);
    var pageData = filteredData.slice(start, end);

    if (pageData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9"><div class="empty"><div class="emoji">📭</div>暂无访问记录</div></td></tr>';
    } else {
        var html = '';
        pageData.forEach(function(v, i) {
            var idx = start + i + 1;
            var flag = codeToFlag(v.country_code);
            var ua = v.user_agent || '-';
            // 简化UA显示
            var shortUa = ua;
            if (ua.length > 40) {
                if (ua.indexOf('Chrome') > -1 && ua.indexOf('Edg') > -1) shortUa = 'Edge';
                else if (ua.indexOf('Chrome') > -1) shortUa = 'Chrome';
                else if (ua.indexOf('Firefox') > -1) shortUa = 'Firefox';
                else if (ua.indexOf('Safari') > -1) shortUa = 'Safari';
                else shortUa = ua.substring(0, 35) + '...';
            }
            html += '<tr>';
            html += '<td>' + idx + '</td>';
            html += '<td class="ip-cell" onclick="copyText(\\'' + v.ip + '\\')">' + v.ip + '</td>';
            html += '<td class="flag-cell">' + flag + '</td>';
            html += '<td>' + (v.country || '-') + '</td>';
            html += '<td>' + (v.city || '-') + (v.region && v.region !== '未知' ? '<br><span style="font-size:11px;color:var(--text-muted)">' + v.region + '</span>' : '') + '</td>';
            html += '<td style="font-size:12px">' + (v.isp || '-') + '</td>';
            html += '<td class="ua-cell" title="' + ua.replace(/"/g, '&quot;') + '">' + shortUa + '</td>';
            html += '<td class="time-cell">' + (v.time || '-') + '</td>';
            html += '<td><a class="map-link" href="https://www.google.com/maps?q=' + (v.latitude||0) + ',' + (v.longitude||0) + '" target="_blank">📍地图</a></td>';
            html += '</tr>';
        });
        tbody.innerHTML = html;
    }

    // 分页
    var pagDiv = document.getElementById('pagination');
    if (totalPages <= 1) {
        pagDiv.innerHTML = '<span>共 ' + total + ' 条记录</span>';
        return;
    }
    var phtml = '<button onclick="goPage(' + (currentPage-1) + ')" ' + (currentPage===1?'disabled':'') + '>上一页</button>';
    // 显示页码
    var startP = Math.max(1, currentPage - 3);
    var endP = Math.min(totalPages, currentPage + 3);
    for (var p = startP; p <= endP; p++) {
        phtml += '<button class="' + (p===currentPage?'active':'') + '" onclick="goPage(' + p + ')">' + p + '</button>';
    }
    phtml += '<button onclick="goPage(' + (currentPage+1) + ')" ' + (currentPage===totalPages?'disabled':'') + '>下一页</button>';
    phtml += '<span style="margin-left:12px">共 ' + total + ' 条</span>';
    pagDiv.innerHTML = phtml;
}

function goPage(p) {
    var totalPages = Math.ceil(filteredData.length / pageSize) || 1;
    if (p < 1 || p > totalPages) return;
    currentPage = p;
    renderTable();
}

function copyText(text) {
    navigator.clipboard.writeText(text).then(function() {
        alert('已复制: ' + text);
    });
}

function confirmClear() {
    document.getElementById('clearModal').style.display = 'flex';
}
function closeModal() {
    document.getElementById('clearModal').style.display = 'none';
}
function doClear() {
    var token = getCookie(cookieName);
    fetch('/api/admin/clear', {
        method: 'POST',
        headers: {'Authorization': 'Bearer ' + token}
    }).then(function(r) {
        if (r.status === 401) { doLogout(); return; }
        closeModal();
        loadData();
    });
}
</script>
</body>
</html>"""


# ========== 路由 ==========

@app.get("/", response_class=HTMLResponse)
async def get_ip_info(request: Request):
    ip = _get_client_ip(request)
    location = await _fetch_location(ip)

    # 记录访问
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

    json_data = {"ip": ip, "location": location if location else None, "error": None}
    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
    json_raw = json.dumps(json_data, ensure_ascii=False)

    html = HTML_TEMPLATE
    html = html.replace("__IP__", ip)
    html = html.replace("__TIMESTAMP__", timestamp)
    html = html.replace("__COUNTRY_FLAG__", country_flag)
    html = html.replace("__COUNTRY__", location.get("country", "未知"))
    html = html.replace("__COUNTRY_CODE__", location.get("country_code", "未知"))
    html = html.replace("__CITY__", location.get("city", "未知"))
    html = html.replace("__REGION__", location.get("region_name", "未知"))
    html = html.replace("__REGION_NAME__", location.get("region_name", "未知"))
    html = html.replace("__LAT__", str(lat))
    html = html.replace("__LON__", str(lon))
    html = html.replace("__TIMEZONE__", location.get("timezone", "未知"))
    html = html.replace("__ISP__", location.get("isp", "未知"))
    html = html.replace("__AS__", location.get("as", "未知"))
    html = html.replace("__ZIP__", location.get("zip", "未知"))
    html = html.replace("__MAP_BBOX__", map_bbox)
    html = html.replace("__JSON_DATA__", json_str.replace("<", "&lt;").replace(">", "&gt;"))
    html = html.replace("__JSON_RAW__", json_raw)

    return HTMLResponse(content=html)


@app.get("/api/info")
async def get_info_api(request: Request):
    ip = _get_client_ip(request)
    location = await _fetch_location(ip)
    return {"ip": ip, "location": location or None, "error": None}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ========== 管理员API ==========

def _verify_admin(request: Request) -> bool:
    """验证管理员token"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        # 简单token: base64(password)
        import base64
        try:
            decoded = base64.b64decode(token).decode("utf-8")
            return decoded == ADMIN_PASSWORD
        except Exception:
            return False
    return False


@app.post("/api/admin/login")
async def admin_login(request: Request):
    """管理员登录"""
    try:
        body = await request.json()
        pwd = body.get("password", "")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request")

    if pwd != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")

    import base64
    token = base64.b64encode(pwd.encode("utf-8")).decode("utf-8")
    return {"token": token, "message": "登录成功"}


@app.get("/api/admin/visits")
async def admin_get_visits(request: Request):
    """获取所有访问记录"""
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")

    visits = _load_visits()
    return {"visits": visits, "total": len(visits)}


@app.post("/api/admin/clear")
async def admin_clear_visits(request: Request):
    """清空所有访问记录"""
    if not _verify_admin(request):
        raise HTTPException(status_code=401, detail="未授权")

    _save_visits([])
    return {"message": "已清空所有记录"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """管理员后台页面"""
    return HTMLResponse(content=ADMIN_HTML)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
