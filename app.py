from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import httpx
import os

app = FastAPI()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IP位置检测工具</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
            max-width: 600px;
            width: 100%;
            animation: slideUp 0.5s ease-out;
        }
        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        h1 {
            color: #667eea;
            text-align: center;
            margin-bottom: 10px;
            font-size: 32px;
        }
        .subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .info-card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 4px solid #667eea;
        }
        .info-card label {
            font-weight: 600;
            color: #555;
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .info-card .value {
            color: #333;
            font-size: 18px;
            word-break: break-all;
            font-family: 'Courier New', monospace;
        }
        .loading {
            text-align: center;
            color: #667eea;
            font-size: 18px;
            padding: 40px;
        }
        .map-link {
            display: block;
            text-align: center;
            margin-top: 20px;
            padding: 12px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            transition: background 0.3s;
        }
        .map-link:hover {
            background: #5568d3;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #aaa;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌍 IP位置检测</h1>
        <p class="subtitle">实时获取您的IP地址和地理位置信息</p>
        
        {% if ip %}
        <div class="info-card">
            <label>📍 您的IP地址</label>
            <div class="value">{{ ip }}</div>
        </div>
        
        {% if location %}
        <div class="info-card">
            <label>🏙️ 国家/地区</label>
            <div class="value">{{ location.country }} ({{ location.country_code }})</div>
        </div>
        
        <div class="info-card">
            <label>📌 城市</label>
            <div class="value">{{ location.city }}</div>
        </div>
        
        <div class="info-card">
            <label>🗺️ 经纬度</label>
            <div class="value">{{ location.latitude }}, {{ location.longitude }}</div>
        </div>
        
        <div class="info-card">
            <label>🌐 时区</label>
            <div class="value">{{ location.timezone }}</div>
        </div>
        
        <div class="info-card">
            <label>🏢 ISP提供商</label>
            <div class="value">{{ location.isp }}</div>
        </div>
        
        <a href="https://www.google.com/maps?q={{ location.latitude }},{{ location.longitude }}" 
           target="_blank" class="map-link">
           📍 在Google地图上查看位置
        </a>
        {% endif %}
        
        {% elif error %}
        <div class="info-card" style="border-left-color: #e74c3c;">
            <label>⚠️ 错误信息</label>
            <div class="value" style="color: #e74c3c;">{{ error }}</div>
        </div>
        {% endif %}
        
        <div class="footer">
            检测时间: {{ timestamp }} | Powered by FastAPI
        </div>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_ip_info(request: Request):
    # 获取真实IP（考虑代理情况）
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host
    
    location = None
    error = None
    
    # 调用ip-api.com获取地理位置信息（免费，无需API key）
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    location = {
                        "country": data.get("country", "未知"),
                        "country_code": data.get("countryCode", "未知"),
                        "city": data.get("city", "未知"),
                        "latitude": data.get("lat", "未知"),
                        "longitude": data.get("lon", "未知"),
                        "timezone": data.get("timezone", "未知"),
                        "isp": data.get("isp", "未知")
                    }
                else:
                    error = f"地理位置查询失败: {data.get('message', '未知错误')}"
            else:
                error = f"API请求失败: HTTP {response.status_code}"
    except Exception as e:
        error = f"获取位置信息失败: {str(e)}"
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = HTML_TEMPLATE.replace("{{ ip }}", ip)
    html = html.replace("{{ timestamp }}", timestamp)
    
    if location:
        for key, value in location.items():
            html = html.replace(f"{{{{ location.{key} }}}}", str(value))
    else:
        html = html.replace("{{ location.country }}", "未知")
        html = html.replace("{{ location.country_code }}", "未知")
        html = html.replace("{{ location.city }}", "未知")
        html = html.replace("{{ location.latitude }}", "未知")
        html = html.replace("{{ location.longitude }}", "未知")
        html = html.replace("{{ location.timezone }}", "未知")
        html = html.replace("{{ location.isp }}", "未知")
    
    if error:
        html = html.replace("{{ error }}", error)
    else:
        html = html.replace("{{ error }}", "")
    
    return HTMLResponse(content=html)

@app.get("/api/info")
async def get_info_api(request: Request):
    """API接口：返回JSON格式的IP和位置信息"""
    ip = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP"))
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.client.host
    
    result = {"ip": ip, "location": None, "error": None}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    result["location"] = {
                        "country": data.get("country", "未知"),
                        "country_code": data.get("countryCode", "未知"),
                        "city": data.get("city", "未知"),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "timezone": data.get("timezone", "未知"),
                        "isp": data.get("isp", "未知")
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
