import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import redis
import requests
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Connect to Redis using the REDIS_URL provided by Vercel
r = redis.from_url(os.environ.get('REDIS_URL'), decode_responses=True)

# IndiaMart Constants
SEARCH_QUERY = "cocopeat block"
INDIAMART_URL = "https://trade.indiamart.com/tradereact/searchpage"

@app.route('/', methods=['GET'])
def home():
    try:
        with open('index.html', 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html'}
    except:
        return "Dashboard file not found", 404

def add_log(msg):
    log_entry = f"{datetime.now().strftime('%H:%M:%S')} - {msg}"
    r.lpush("monitor_logs", log_entry)
    r.ltrim("monitor_logs", 0, 19) # Keep last 20 logs

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        is_running = r.get("monitor_status") == "true"
        last_check = r.get("last_check_time") or "Never"
        logs = r.lrange("monitor_logs", 0, -1)
        
        min_value = int(r.get("config_min_value") or 300000)
        min_qty_kg = int(r.get("config_min_qty_kg") or 10000)
        
    except Exception as e:
        return jsonify({"error": "Redis error", "details": str(e)}), 500

    return jsonify({
        "isRunning": is_running,
        "lastStatus": f"Last checked: {last_check}",
        "ntfyTopic": r.get("ntfy_topic") or "configure_me",
        "logs": logs,
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
        r.set("config_min_value", str(min_value))
    if min_qty_kg is not None:
        r.set("config_min_qty_kg", str(min_qty_kg))
    return jsonify({"success": True})

@app.route('/api/toggle', methods=['POST'])
def toggle_monitor():
    data = request.json
    enable = data.get('enable', False)
    r.set("monitor_status", "true" if enable else "false")
    if not r.get("ntfy_topic"):
        import uuid
        r.set("ntfy_topic", f"indiamart_cocopeat_{uuid.uuid4().hex[:8]}")
    return jsonify({"isRunning": enable})

@app.route('/api/test_notify', methods=['POST'])
def test_notify():
    ntfy_topic = r.get("ntfy_topic")
    if ntfy_topic:
        requests.post(f"https://ntfy.sh/{ntfy_topic}", data="Vercel Cloud Test: Your notification system is working!".encode('utf-8'), headers={"Title": "Cloud Test", "Priority": "high"})
    return jsonify({"success": True})

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
    
    if r.get("monitor_status") != "true":
        return "Monitor is OFF", 200

    min_val_limit = int(r.get("config_min_value") or 300000)
    min_qty_limit = int(r.get("config_min_qty_kg") or 10000)

    try:
        add_log("Starting scan...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://trade.indiamart.com",
            "Referer": "https://trade.indiamart.com/buyersearch.mp?ss=cocopeat+block"
        }
        payload = {"source": "eto.search.lead", "q": SEARCH_QUERY, "options.start": 0, "options.results": 20}
        
        response = requests.post(INDIAMART_URL, data=payload, headers=headers, timeout=15)
        
        if response.status_code != 200:
            add_log(f"IndiaMart Error {response.status_code}. Possible block.")
            return f"IndiaMart blocked the request (Status {response.status_code})", response.status_code

        try:
            data = response.json()
        except:
            add_log("Error: IndiaMart sent HTML instead of Data. Being blocked.")
            return "IndiaMart Blocked (HTML received)", 500

        results = data.get("results", [])
        add_log(f"Found {len(results)} leads.")
        
        ntfy_topic = r.get("ntfy_topic")
        matches_found = 0
        
        for lead in results:
            fields = lead.get("fields", {})
            display_id = fields.get("displayid")
            if not display_id or r.sismember("seen_leads", display_id): continue
                
            isq = fields.get("isqdetails", [])
            total_qty = 0
            max_value = 0
            for detail in isq:
                if "quantity" in detail.lower(): total_qty = parse_quantity(detail)
                if "value" in detail.lower(): max_value = parse_value(detail)

            matches_qty = (min_qty_limit > 0 and total_qty >= min_qty_limit)
            matches_val = (min_val_limit > 0 and max_value >= min_val_limit)

            if matches_qty or matches_val:
                title = fields.get("title", "Lead")
                city = fields.get("city", "Unknown")
                details_all = "\n".join([f"- {d}" for d in isq])
                msg = f"Product: {title}\nLocation: {city}\nQty: {total_qty} KG\nValue: Rs. {max_value:,.0f}\n\n{details_all}"
                requests.post(f"https://ntfy.sh/{ntfy_topic}", data=msg.encode('utf-8'), headers={"Title": "MATCH!", "Priority": "high"})
                matches_found += 1
                add_log(f"Match sent: {title}")

            r.sadd("seen_leads", display_id)

        add_log(f"Scan complete. {matches_found} notifications sent.")
        r.set("last_check_time", datetime.now().strftime('%H:%M:%S'))
        return "OK", 200
    except Exception as e:
        add_log(f"Scan error: {str(e)}")
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    app.run()
