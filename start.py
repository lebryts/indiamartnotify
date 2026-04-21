import subprocess
import sys
import time
import os

def run():
    print("🚀 Starting IndiaMart Lead Notifier...")
    
    # Path to venv python
    venv_python = os.path.join(os.getcwd(), "venv", "bin", "python")
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable
    
    if python_exe == sys.executable:
        print("⚠️ Virtual environment not found. Using system python.")
    else:
        print(f"Using virtual environment: {python_exe}")

    # Path to logs
    os.makedirs("logs", exist_ok=True)

    # Start Backend
    print("Starting Backend (Port 5000)...")
    backend = subprocess.Popen([python_exe, "backend/app.py"], 
                               stdout=open("logs/backend.log", "w"), 
                               stderr=subprocess.STDOUT)

    # Start Frontend
    print("Starting Frontend (Port 8080)...")
    frontend = subprocess.Popen([python_exe, "-m", "http.server", "8080", "--directory", "frontend"], 
                                stdout=open("logs/frontend.log", "w"), 
                                stderr=subprocess.STDOUT)

    print("\n✅ System is running!")
    print("1. Open http://localhost:8080 on your phone/computer")
    print("2. Follow the instructions on the screen to set up notifications")
    print("3. Keep this window open.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        backend.terminate()
        frontend.terminate()
        print("Done.")

if __name__ == "__main__":
    run()
