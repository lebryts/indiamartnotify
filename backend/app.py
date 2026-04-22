from flask import Flask, jsonify, request
from flask_cors import CORS
from monitor import monitor, NTFY_TOPIC

app = Flask(__name__)
CORS(app)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "isRunning": monitor.is_running,
        "lastStatus": monitor.last_status,
        "ntfyTopic": NTFY_TOPIC,
        "logs": [],
        "config": {
            "minValue": monitor.min_value,
            "minQtyKg": monitor.min_qty_kg
        }
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    monitor.min_value = int(data.get('minValue', monitor.min_value))
    monitor.min_qty_kg = int(data.get('minQtyKg', monitor.min_qty_kg))
    return jsonify({"success": True})

@app.route('/api/toggle', methods=['POST'])
def toggle_monitor():
    data = request.json
    enable = data.get('enable', False)
    
    if enable and not monitor.is_running:
        monitor.start()
    elif not enable and monitor.is_running:
        monitor.stop()
        
@app.route('/api/test_notify', methods=['POST'])
def test_notify():
    data = {"Title": "Test Alert", "Priority": "high", "Tags": "tada"}
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data="This is a test notification from your IndiaMart app!".encode('utf-8'), headers=data)
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
