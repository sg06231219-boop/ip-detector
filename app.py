from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import httpx
import os
import json
from datetime import datetime

app = FastAPI()

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
        /* 粒子画布 */
        #particles {
            position: fixed; top:0; left:0; width:100%; height:100%;
            z-index: 0; pointer-events: none;
        }
        /* 主容器 */
        .wrapper {
            position: relative; z-index: 1;
            max-width: 900px; margin: 0 auto; padding: 30px 20px;
        }
        /* 头部 */
        .header {
            text-align: center; padding: 40px 0 30px;
            animation: fadeInDown 0.6s ease-out;
        }
        .header h1 {
            font-size: 42px; font-weight: 800;
            background: linear-gradient(135deg, var(--accent), var(--accent2), var(--accent3));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }
        .header p { color: var(--text-secondary); font-size: 15px; }
        /* 状态指示 */
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
        /* IP大字展示 */
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
        /* 信息网格 */
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
        /* 各卡片配色 */
        .card-location .card-icon { background: rgba(124,77,255,0.15); }
        .card-city .card-icon { background: rgba(68,138,255,0.15); }
        .card-coords .card-icon { background: rgba(24,255,255,0.15); }
        .card-timezone .card-icon { background: rgba(255,214,0,0.15); }
        .card-isp .card-icon { background: rgba(105,240,174,0.15); }
        .card-region .card-icon { background: rgba(255,82,82,0.15); }
        .card-as .card-icon { background: rgba(255,145,0,0.15); }
        .card-browser .card-icon { background: rgba(234,128,252,0.15); }
        /* 地图 */
        .map-section {
            margin: 30px 0;
            animation: fadeInUp 0.6s ease-out 0.8s both;
        }
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
        /* 操作按钮 */
        .actions {
            display: flex; gap: 12px; flex-wrap: wrap;
            margin: 24px 0;
            animation: fadeInUp 0.6s ease-out 1s both;
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
        /* Toast通知 */
        .toast {
            position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(100px);
            background: var(--bg-secondary); border: 1px solid var(--accent);
            color: var(--text-primary); padding: 12px 24px; border-radius: 12px;
            font-size: 14px; z-index: 1000;
            transition: transform 0.3s ease; pointer-events: none;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        .toast.show { transform: translateX(-50%) translateY(0); }
        /* 详情JSON折叠 */
        .json-section {
            margin: 30px 0;
            animation: fadeInUp 0.6s ease-out 1.2s both;
        }
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
        /* 页脚 */
        .footer {
            text-align: center; padding: 30px 0 20px;
            color: var(--text-muted); font-size: 12px;
            border-top: 1px solid var(--border); margin-top: 40px;
        }
        .footer a { color: var(--accent2); text-decoration: none; }
        /* 动画 */
        @keyframes fadeInUp {
            from { opacity:0; transform:translateY(20px); }
            to { opacity:1; transform:translateY(0); }
        }
        @keyframes fadeInDown {
            from { opacity:0; transform:translateY(-20px); }
            to { opacity:1; transform:translateY(0); }
        }
        /* 信息卡片交错动画延迟 */
        .info-card:nth-child(1) { animation-delay: 0.3s; }
        .info-card:nth-child(2) { animation-delay: 0.4s; }
        .info-card:nth-child(3) { animation-delay: 0.5s; }
        .info-card:nth-child(4) { animation-delay: 0.6s; }
        .info-card:nth-child(5) { animation-delay: 0.7s; }
        .info-card:nth-child(6) { animation-delay: 0.8s; }
        .info-card:nth-child(7) { animation-delay: 0.9s; }
        .info-card:nth-child(8) { animation-delay: 1.0s; }
        /* 移动端适配 */
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
        <!-- 头部 -->
        <div class="header">
            <h1>🌍 IP 智能定位</h1>
            <p>实时检测您的网络身份与地理位置</p>
            <div class="status-badge">
                <span class="status-dot"></span>
                检测完成 · __TIMESTAMP__
            </div>
        </div>

        <!-- IP大字 -->
        <div class="ip-hero">
            <div class="ip-label">您的公网 IP 地址</div>
            <div class="ip-value" onclick="copyIP()" title="点击复制">__IP__</div>
            <div class="copy-hint">点击IP即可复制</div>
        </div>

        <!-- 信息卡片 -->
        <div class="info-grid" id="infoGrid">
            <div class="info-card card-location">
                <div class="card-header">
                    <div class="card-icon">🏳️</div>
                    <div class="card-title">国家/地区</div>
                </div>
                <div class="card-value" id="country">__COUNTRY_FLAG__ __COUNTRY__</div>
                <div class="card-sub">代码: __COUNTRY_CODE__</div>
            </div>
            <div class="info-card card-city">
                <div class="card-header">
                    <div class="card-icon">🏙️</div>
                    <div class="card-title">城市</div>
                </div>
                <div class="card-value" id="city">__CITY__</div>
                <div class="card-sub" id="regionSub">地区: __REGION__</div>
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

        <!-- 内嵌地图 -->
        <div class="map-section">
            <h3>📍 地理位置可视化</h3>
            <div class="map-container">
                <iframe src="https://www.openstreetmap.org/export/embed.html?bbox=__MAP_BBOX__&layer=mapnik&marker=__LAT__,__LON__" loading="lazy"></iframe>
            </div>
        </div>

        <!-- 操作按钮 -->
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

        <!-- JSON详情折叠 -->
        <div class="json-section">
            <button class="json-toggle" onclick="toggleJSON(this)">
                <span class="arrow">▶</span> 查看 JSON 原始数据
            </button>
            <div class="json-content" id="jsonContent">__JSON_DATA__</div>
        </div>

        <!-- 页脚 -->
        <div class="footer">
            IP智能定位工具 · 数据来源 ip-api.com · 检测时间 __TIMESTAMP__<br>
            <span style="opacity:0.5;">位置为大致估算，不代表精确住址</span>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <script>
    // 粒子背景
    (function() {
        var c = document.getElementById('particles');
        var ctx = c.getContext('2d');
        var particles = [];
        var count = 60;

        function resize() {
            c.width = window.innerWidth;
            c.height = window.innerHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        for (var i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * c.width,
                y: Math.random() * c.height,
                vx: (Math.random() - 0.5) * 0.3,
                vy: (Math.random() - 0.5) * 0.3,
                r: Math.random() * 1.5 + 0.5,
                o: Math.random() * 0.4 + 0.1
            });
        }

        function draw() {
            ctx.clearRect(0, 0, c.width, c.height);
            for (var i = 0; i < particles.length; i++) {
                var p = particles[i];
                p.x += p.vx; p.y += p.vy;
                if (p.x < 0) p.x = c.width;
                if (p.x > c.width) p.x = 0;
                if (p.y < 0) p.y = c.height;
                if (p.y > c.height) p.y = 0;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(124,77,255,' + p.o + ')';
                ctx.fill();
                // 连线
                for (var j = i + 1; j < particles.length; j++) {
                    var q = particles[j];
                    var dx = p.x - q.x, dy = p.y - q.y;
                    var dist = Math.sqrt(dx*dx + dy*dy);
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(q.x, q.y);
                        ctx.strokeStyle = 'rgba(124,77,255,' + (0.08 * (1 - dist/120)) + ')';
                        ctx.stroke();
                    }
                }
            }
            requestAnimationFrame(draw);
        }
        draw();
    })();

    // 浏览器检测
    (function() {
        var ua = navigator.userAgent;
        var browser = '未知';
        if (ua.indexOf('Edg') > -1) browser = 'Microsoft Edge';
        else if (ua.indexOf('Chrome') > -1) browser = 'Google Chrome';
        else if (ua.indexOf('Firefox') > -1) browser = 'Mozilla Firefox';
        else if (ua.indexOf('Safari') > -1) browser = 'Apple Safari';
        else if (ua.indexOf('Opera') > -1) browser = 'Opera';
        document.getElementById('browserInfo').textContent = browser;
        document.getElementById('screenInfo').textContent = screen.width + 'x' + screen.height + ' · ' + (navigator.language || '未知');
    })();

    // 本地时间
    (function() {
        try {
            var tz = '__TIMEZONE__';
            if (tz && tz !== '未知') {
                var now = new Date();
                var opts = { timeZone: tz, hour12: false, year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit' };
                document.getElementById('localTime').textContent = '本地时间: ' + now.toLocaleString('zh-CN', opts);
            }
        } catch(e) {}
    })();

    // 复制IP
    function copyIP() {
        navigator.clipboard.writeText('__IP__').then(function() {
            showToast('✅ IP地址已复制到剪贴板');
        });
    }

    // 复制全部
    function copyAll() {
        var data = __JSON_RAW__;
        var text = 'IP地址: ' + data.ip + '\\n';
        if (data.location) {
            var l = data.location;
            text += '国家: ' + l.country + ' (' + l.country_code + ')\\n';
            text += '城市: ' + l.city + '\\n';
            text += '地区: ' + (l.region_name || '未知') + '\\n';
            text += '经纬度: ' + l.latitude + ', ' + l.longitude + '\\n';
            text += '时区: ' + l.timezone + '\\n';
            text += 'ISP: ' + l.isp + '\\n';
            text += 'AS: ' + (l.as || '未知') + '\\n';
        }
        navigator.clipboard.writeText(text).then(function() {
            showToast('✅ 全部信息已复制到剪贴板');
        });
    }

    // Toast
    function showToast(msg) {
        var t = document.getElementById('toast');
        t.textContent = msg;
        t.classList.add('show');
        setTimeout(function() { t.classList.remove('show'); }, 2000);
    }

    // JSON折叠
    function toggleJSON(btn) {
        btn.classList.toggle('open');
        document.getElementById('jsonContent').classList.toggle('show');
    }
    </script>
</body>
</html>"""


def get_country_flag(code: str) -> str:
    """将国家代码转换为国旗emoji"""
    if not code or len(code) != 2:
        return "🏁"
    try:
        offset = 127397  # 🇦 = 127462, A = 65, 127462 - 65 = 127397
        return chr(ord(code[0].upper()) + offset) + chr(ord(code[1].upper()) + offset)
    except Exception:
        return "🏁"


@app.get("/", response_class=HTMLResponse)
async def get_ip_info(request: Request):
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host

    location = {}
    error = None

    try:
        async with httpx.AsyncClient() as client:
            # ip-api.com 批量字段查询
            fields = "status,message,country,countryCode,city,lat,lon,timezone,isp,as,regionName,zip"
            resp = await client.get(
                f"http://ip-api.com/json/{ip}?lang=zh-CN&fields={fields}",
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    location = {
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
                else:
                    error = data.get("message", "查询失败")
            else:
                error = f"HTTP {resp.status_code}"
    except Exception as e:
        error = str(e)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    country_flag = get_country_flag(location.get("country_code", ""))
    lat = location.get("latitude", 0)
    lon = location.get("longitude", 0)

    # 地图bbox (小范围)
    try:
        d = 0.05
        lat_f, lon_f = float(lat), float(lon)
        map_bbox = f"{lon_f-d},{lat_f-d},{lon_f+d},{lat_f+d}"
    except (ValueError, TypeError):
        map_bbox = "112.5,37.8,112.6,37.9"

    # JSON数据（给前端JS使用）
    json_data = {"ip": ip, "location": location if location else None, "error": error}
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
    """JSON API"""
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host

    result = {"ip": ip, "location": None, "error": None}
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
                    result["location"] = {
                        "country": data.get("country", "未知"),
                        "country_code": data.get("countryCode", "未知"),
                        "city": data.get("city", "未知"),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "timezone": data.get("timezone", "未知"),
                        "isp": data.get("isp", "未知"),
                        "as": data.get("as", "未知"),
                        "region_name": data.get("regionName", "未知"),
                        "zip": data.get("zip", "未知"),
                    }
    except Exception as e:
        result["error"] = str(e)
    return result


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
