import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import redis
import requests
import re
import random
import time
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
CORS(app)

# Connect to Redis
r = redis.from_url(os.environ.get('REDIS_URL'), decode_responses=True)

DEFAULT_SEARCH_URL = "https://trade.indiamart.com/buyersearch.mp?ss=cocopeat+block&src=as-popular%7Ckwd%3Dcocopeat+blo%7Cpos%3D1%7Ccat%3D-2%7Cmcat%3D-2%7Ckwd_len%3D12%7Ckwd_cnt%3D2"

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
        search_query = r.get("config_search_query") or "cocopeat block"
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
    
    # Safety Cooldown: Don't scan more than once every 2 minutes
    last_run_timestamp = r.get("last_run_timestamp")
    current_time = int(time.time())
    if last_run_timestamp and (current_time - int(last_run_timestamp) < 120):
        if is_manual:
            add_log("Too frequent! Wait 2 mins.")
            return "Cooldown active", 200
        return "Too early", 200

    if not is_manual and r.get("monitor_status") != "true":
        return "Monitor is OFF", 200

    r.set("last_run_timestamp", str(current_time))

    min_val_limit = int(r.get("config_min_value") or 300000)
    min_qty_limit = int(r.get("config_min_qty_kg") or 10000)
    search_query = r.get("config_search_query") or "cocopeat block"

    # Construct the URL
    url = f"https://trade.indiamart.com/buyersearch.mp?ss={search_query.replace(' ', '+')}&src=as-popular%7Ckwd%3Dcocopeat+blo%7Cpos%3D1%7Ccat%3D-2%7Cmcat%3D-2%7Ckwd_len%3D12%7Ckwd_cnt%3D2"

    try:
        add_log(f"Scraping Desktop: {search_query}")
        
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]

        headers = {
            "User-Agent": random.choice(user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://trade.indiamart.com/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        
        cookie = os.environ.get("INDIAMART_COOKIE")
        if cookie:
            headers["Cookie"] = cookie

        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 429:
            add_log("Error 429: Rate Limited.")
            return "Rate Limited", 200
            
        if response.status_code != 200:
            add_log(f"IndiaMart Error {response.status_code}.")
            return f"Error {response.status_code}", 200

        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.find_all(class_='TRA_card')
        
        if not cards:
            # Try a broader search if the specific class isn't found
            cards = soup.select('[class*="card"]')
            
        add_log(f"Found {len(cards)} cards on page.")
        
        ntfy_topic = r.get("ntfy_topic")
        new_leads_count = 0
        
        for card in cards:
            text = card.get_text(separator=' ', strip=True)
            
            # Extract Lead ID from link
            link_el = card.find('a', href=True)
            if not link_el: continue
            
            href = link_el['href']
            parsed_url = urlparse(href)
            params = parse_qs(parsed_url.query)
            display_id = params.get('offer', [None])[0]
            
            if not display_id or r.sismember("seen_leads", display_id): continue
            
            # Extract Quantity and Value using regex from the card text
            qty_match = re.search(r"Quantity\s*:\s*([^:]+?)(?=Probable|Member|Mobile|$)", text, re.I)
            val_match = re.search(r"Probable Order Value\s*:\s*([^:]+?)(?=Member|Mobile|$)", text, re.I)
            
            qty_text = qty_match.group(1).strip() if qty_match else "0"
            val_text = val_match.group(1).strip() if val_match else "0"
            
            total_qty = parse_quantity(qty_text)
            max_value = parse_value(val_text)

            matches_qty = (total_qty >= min_qty_limit)
            matches_val = (max_value >= min_val_limit)

            if matches_qty or matches_val:
                title = link_el.get_text().strip() or "New Lead"
                # City is usually after the title in the card
                city_match = re.search(r"(?:Yesterday|hr ago|hrs ago|min ago)\s+(.*)", text)
                city = city_match.group(1).strip().split(' ')[0] if city_match else "Unknown"
                
                msg = f"Product: {title}\nLocation: {city}\nQty: {qty_text}\nValue: {val_text}"
                requests.post(f"https://ntfy.sh/{ntfy_topic}", data=msg.encode('utf-8'), headers={"Title": "Desktop Match!", "Priority": "high"})
                add_log(f"Alert Sent: {city}")
                new_leads_count += 1

            r.sadd("seen_leads", display_id)
        
        r.expire("seen_leads", 604800)
        r.set("last_check_time", datetime.now().strftime('%H:%M:%S'))
        return "OK", 200
    except Exception as e:
        add_log(f"Scrape failed: {str(e)[:50]}")
        import traceback
        print(traceback.format_exc())
        return f"Error: {str(e)}", 200

if __name__ == '__main__':
    app.run()
