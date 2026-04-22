import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import redis
import requests
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Connect to Redis
r = redis.from_url(os.environ.get('REDIS_URL'), decode_responses=True)

# IndiaMart Mobile Constants
DEFAULT_SEARCH_QUERY = "cocopeat block"
# Using the exact mobile URL from your screenshot
MOBILE_API_URL = "https://m.indiamart.com/ajaxrequest/identified/buyleads/bl/search"

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
    r.ltrim("monitor_logs", 0, 19)

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        is_running = r.get("monitor_status") == "true"
        last_check = r.get("last_check_time") or "Never"
        logs = r.lrange("monitor_logs", 0, -1)
        min_value = int(r.get("config_min_value") or 300000)
        min_qty_kg = int(r.get("config_min_qty_kg") or 10000)
        search_query = r.get("config_search_query") or DEFAULT_SEARCH_QUERY
    except Exception as e:
        return jsonify({"error": "Redis error", "details": str(e)}), 500
    return jsonify({
        "isRunning": is_running,
        "lastStatus": f"Last checked: {last_check}",
        "ntfyTopic": r.get("ntfy_topic") or "configure_me",
        "logs": logs,
        "config": {
            "minValue": min_value, 
            "minQtyKg": min_qty_kg,
            "searchQuery": search_query
        }
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    if data.get('minValue') is not None: r.set("config_min_value", str(data.get('minValue')))
    if data.get('minQtyKg') is not None: r.set("config_min_qty_kg", str(data.get('minQtyKg')))
    if data.get('searchQuery') is not None: r.set("config_search_query", str(data.get('searchQuery')))
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
        requests.post(f"https://ntfy.sh/{ntfy_topic}", data="Testing ntfy from Vercel!".encode('utf-8'), headers={"Title": "Cloud Test", "Priority": "high"})
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
    is_manual = request.args.get("manual") == "true"
    
    if not is_manual and secret_key and request.args.get("key") != secret_key:
        return "Unauthorized", 401
    
    if not is_manual and r.get("monitor_status") != "true":
        return "Monitor is OFF", 200

    min_val_limit = int(r.get("config_min_value") or 300000)
    min_qty_limit = int(r.get("config_min_qty_kg") or 10000)
    search_query = r.get("config_search_query") or DEFAULT_SEARCH_QUERY

    try:
        add_log(f"Scanning for: {search_query}")
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://m.indiamart.com/bl/search.php?s={search_query.replace(' ', '+')}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        cookie = os.environ.get("INDIAMART_COOKIE")
        if cookie:
            headers["Cookie"] = cookie
            # add_log("Using mobile session cookie.") # Quiet this log to save space

        params = {
            "q": search_query,
            "start": 0,
            "rows": 20,
            "src": "DirectSearch"
        }
        
        response = requests.get(MOBILE_API_URL, params=params, headers=headers, timeout=25)
        
        if response.status_code != 200:
            add_log(f"IndiaMart Error {response.status_code}.")
            return f"Error {response.status_code}", 200 # Return 200 to cron-job.org to avoid 'failure' emails if it's just a temp block

        data = response.json()
        # Some responses might be errors wrapped in JSON
        if not data.get("data") and data.get("message"):
            add_log(f"IM Msg: {data.get('message')}")
            if "login" in data.get("message").lower():
                add_log("Cookie probably expired!")

        results = data.get("data", [])
        add_log(f"Found {len(results)} leads.")
        
        ntfy_topic = r.get("ntfy_topic")
        new_leads_count = 0
        
        for lead in results:
            # Try both uppercase and lowercase for robustness
            display_id = lead.get("DISPLAY_ID") or lead.get("display_id") or lead.get("DISPLAYID")
            if not display_id or r.sismember("seen_leads", display_id): continue
                
            qty_text = str(lead.get("QUANTITY") or lead.get("quantity") or "0")
            val_text = str(lead.get("PROBABLE_ORDER_VALUE") or lead.get("probable_order_value") or "0")
            
            total_qty = parse_quantity(qty_text)
            max_value = parse_value(val_text)

            matches_qty = (min_qty_limit > 0 and total_qty >= min_qty_limit)
            matches_val = (min_val_limit > 0 and max_value >= min_val_limit)

            if matches_qty or matches_val:
                title = lead.get("SUBJECT") or lead.get("subject") or "Lead"
                city = lead.get("CITY") or lead.get("city") or "Unknown"
                msg = f"Product: {title}\nLocation: {city}\nQty: {qty_text}\nValue: {val_text}"
                requests.post(f"https://ntfy.sh/{ntfy_topic}", data=msg.encode('utf-8'), headers={"Title": "Lead Match!", "Priority": "high"})
                add_log(f"Alert Sent: {city}")
                new_leads_count += 1

            r.sadd("seen_leads", display_id)
        
        # Set TTL for seen_leads to 7 days
        r.expire("seen_leads", 604800)

        r.set("last_check_time", datetime.now().strftime('%H:%M:%S'))
        return "OK", 200
    except Exception as e:
        add_log(f"Scan failed: {str(e)[:50]}")
        return f"Error: {str(e)}", 200

if __name__ == '__main__':
    app.run()
