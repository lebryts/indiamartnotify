import os
import time
import requests
import re
from datetime import datetime
from threading import Thread

# Configuration
SEARCH_QUERY = "cocopeat block"
POLL_INTERVAL = 60  # 5 minutes
NTFY_TOPIC = "indiamart_cocopeat_leads_" + os.urandom(4).hex()  # Unique topic
INDIAMART_URL = "https://trade.indiamart.com/tradereact/searchpage"

# User Requirements
MIN_VALUE = 300000  # 3 Lakhs
MIN_QUANTITY_KG = 10000  # 10 Tons

class LeadMonitor:
    def __init__(self):
        self.is_running = False
        self.seen_leads = set()
        self.last_status = "Initialized"

    def parse_quantity(self, qty_str):
        """Extracts quantity in KG from string like 'Quantity:20 Kg' or '10 Tonne'"""
        qty_str = qty_str.lower().replace("quantity:", "").strip()
        match = re.search(r"(\d+(\.\d+)?)", qty_str)
        if not match:
            return 0
        
        value = float(match.group(1))
        
        if "ton" in qty_str or "mt" in qty_str:
            return value * 1000
        elif "kg" in qty_str:
            return value
        return value # Default to KG if unknown but has number

    def parse_value(self, val_str):
        """Extracts max value from string like 'Probable Order Value:Rs. 2 to 5 Lakh'"""
        val_str = val_str.lower().replace("probable order value:", "").strip()
        
        # Handle 'Lakh'
        multiplier = 1
        if "lakh" in val_str:
            multiplier = 100000
        elif "cr" in val_str:
            multiplier = 10000000

        # Find all numbers
        numbers = re.findall(r"(\d+(\.\d+)?)", val_str)
        if not numbers:
            return 0
        
        # Get the highest number in the range
        max_val = max([float(n[0]) for n in numbers])
        return max_val * multiplier

    def check_leads(self):
        print(f"Checking Indiamart for {SEARCH_QUERY}...")
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
            response = requests.post(INDIAMART_URL, data=payload, headers=headers, timeout=20)
            data = response.json()
            
            results = data.get("results", [])
            for lead in results:
                fields = lead.get("fields", {})
                display_id = fields.get("displayid")
                
                if not display_id or display_id in self.seen_leads:
                    continue
                
                # Initial run: just mark existing leads as seen
                if not self.seen_leads:
                    self.seen_leads.add(display_id)
                    continue

                self.process_lead(fields)
                self.seen_leads.add(display_id)

            self.last_status = f"Last checked: {datetime.now().strftime('%H:%M:%S')}"
        except Exception as e:
            self.last_status = f"Error: {str(e)}"
            print(f"Error checking leads: {e}")

    def process_lead(self, fields):
        title = fields.get("title", "Unknown Product")
        city = fields.get("city", "Unknown")
        isq = fields.get("isqdetails", [])
        
        total_qty = 0
        max_value = 0
        
        details_text = ""
        for detail in isq:
            details_text += f"- {detail}\n"
            if "quantity" in detail.lower():
                total_qty = self.parse_quantity(detail)
            if "value" in detail.lower():
                max_value = self.parse_value(detail)

        # Filtering Logic
        matches_qty = total_qty >= MIN_QUANTITY_KG
        matches_val = max_value >= MIN_VALUE
        
        if matches_qty or matches_val:
            print(f"MATCH FOUND: {title} in {city}")
            self.send_notification(title, city, total_qty, max_value, details_text)

    def send_notification(self, title, city, qty, val, details):
        msg = f"New High-Value Lead!\n\nProduct: {title}\nLocation: {city}\n"
        msg += f"Qty: {qty} KG\nValue: Rs. {val:,.0f}\n\n{details}"
        
        try:
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
                          data=msg.encode('utf-8'),
                          headers={
                              "Title": "IndiaMart Alert: Cocopeat",
                              "Priority": "high",
                              "Tags": "money,shopping_bags"
                          })
        except Exception as e:
            print(f"Failed to send notification: {e}")

    def start(self):
        self.is_running = True
        self.seen_leads.clear()
        
        def run_loop():
            while self.is_running:
                self.check_leads()
                time.sleep(POLL_INTERVAL)
        
        Thread(target=run_loop, daemon=True).start()

    def stop(self):
        self.is_running = False
        self.last_status = "Stopped"

monitor = LeadMonitor()
