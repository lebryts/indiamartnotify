import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from upstash_redis import Redis
import requests
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Connect to Redis
redis = Redis.from_env()

# IndiaMart Constants
SEARCH_QUERY = "cocopeat block"
INDIAMART_URL = "https://trade.indiamart.com/tradereact/searchpage"

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        is_running = redis.get("monitor_status") == "true"
        last_check = redis.get("last_check_time") or "Never"
        
        # Get dynamic config or use defaults
        min_value = int(redis.get("config_min_value") or 300000)
        min_qty_kg = int(redis.get("config_min_qty_kg") or 10000)
        
    except Exception as e:
        return jsonify({"error": "KV not configured", "details": str(e)}), 500

    return jsonify({
        "isRunning": is_running,
        "lastStatus": f"Last checked: {last_check}",
        "ntfyTopic": redis.get("ntfy_topic") or "configure_me",
        "config": {
            "minValue": min_value,
            "minQtyKg": min_qty_kg
        }
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    min_value = data.get('minValue')
    min_qty_kg = data.get('minQtyKg')
    
    if min_value is not None:
        redis.set("config_min_value", str(min_value))
    if min_qty_kg is not None:
        redis.set("config_min_qty_kg", str(min_qty_kg))
        
    return jsonify({"success": True})

@app.route('/api/toggle', methods=['POST'])
def toggle_monitor():
    data = request.json
    enable = data.get('enable', False)
    redis.set("monitor_status", "true" if enable else "false")
    if not redis.get("ntfy_topic"):
        import uuid
        redis.set("ntfy_topic", f"indiamart_cocopeat_{uuid.uuid4().hex[:8]}")
    return jsonify({"isRunning": enable})

def parse_quantity(qty_str):
    qty_str = qty_str.lower().replace("quantity:", "").strip()
    match = re.search(r"(\d+(\.\d+)?)", qty_str)
    if not match: return 0
    value = float(match.group(1))
    if "ton" in qty_str or "mt" in qty_str: return value * 1000
    return value

def parse_value(val_str):
    val_str = val_str.lower().replace("probable order value:", "").strip()
    multiplier = 100000 if "lakh" in val_str else 10000000 if "cr" in val_str else 1
    numbers = re.findall(r"(\d+(\.\d+)?)", val_str)
    if not numbers: return 0
    return max([float(n[0]) for n in numbers]) * multiplier

@app.route('/api/cron', methods=['GET'])
def run_cron():
    secret_key = os.environ.get("CRON_SECRET")
    if secret_key and request.args.get("key") != secret_key:
        return "Unauthorized", 401
    
    if redis.get("monitor_status") != "true":
        return "Monitor is OFF", 200

    # Get dynamic config
    min_val_limit = int(redis.get("config_min_value") or 300000)
    min_qty_limit = int(redis.get("config_min_qty_kg") or 10000)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://trade.indiamart.com/buyersearch.mp?ss=cocopeat+block"
    }
    
    payload = {
        "source": "eto.search.lead",
        "q": SEARCH_QUERY,
        "options.start": 0,
        "options.results": 20
    }

    try:
        response = requests.post(INDIAMART_URL, data=payload, headers=headers, timeout=15)
        data = response.json()
        results = data.get("results", [])
        ntfy_topic = redis.get("ntfy_topic")
        
        for lead in results:
            fields = lead.get("fields", {})
            display_id = fields.get("displayid")
            if not display_id or redis.sismember("seen_leads", display_id): continue
                
            isq = fields.get("isqdetails", [])
            total_qty = 0
            max_value = 0
            for detail in isq:
                if "quantity" in detail.lower(): total_qty = parse_quantity(detail)
                if "value" in detail.lower(): max_value = parse_value(detail)

            if total_qty >= min_qty_limit or max_value >= min_val_limit:
                title = fields.get("title", "Lead")
                city = fields.get("city", "Unknown")
                details_all = "\n".join([f"- {d}" for d in isq])
                msg = f"Product: {title}\nLocation: {city}\nQty: {total_qty} KG\nValue: Rs. {max_value:,.0f}\n\n{details_all}"
                requests.post(f"https://ntfy.sh/{ntfy_topic}", data=msg.encode('utf-8'), headers={"Title": "Lead Match!", "Priority": "high"})

            redis.sadd("seen_leads", display_id)

        redis.set("last_check_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return "OK", 200
    except Exception as e:
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    app.run()
