from flask import Flask, jsonify, request
from flask_cors import CORS
from monitor import monitor, NTFY_TOPIC

app = Flask(__name__)
CORS(app)

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        "isRunning": monitor.is_running,
        "lastStatus": monitor.last_status,
        "ntfyTopic": NTFY_TOPIC,
        "config": {
            "minValue": 300000,
            "minQtyKg": 10000
        }
    })

@app.route('/toggle', methods=['POST'])
def toggle_monitor():
    data = request.json
    enable = data.get('enable', False)
    
    if enable and not monitor.is_running:
        monitor.start()
    elif not enable and monitor.is_running:
        monitor.stop()
        
    return jsonify({"isRunning": monitor.is_running})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
