import os
import signal
import shutil
import sys
import asyncio
import subprocess
import contextlib
import logging
import uvicorn
import aiosqlite
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import List, Dict, Any


# ---- Suppress noisy /api/refresh access logs ----
class RefreshLogFilter(logging.Filter):
    """Filters out access log entries for the /api/refresh polling endpoint."""
    def filter(self, record):
        msg = record.getMessage()
        if '/api/refresh' in msg:
            return False
        return True

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting SkyTracker API...")
    # Start background telemetry engine to decouple DB from HTTP UI
    asyncio.create_task(update_telemetry_loop())
    try:
        check_dependencies()
    except RuntimeError as e:
        print(f"WARNING: {e}")
    yield
    # Cleanup on shutdown could go here if needed

app = FastAPI(title="SkyTracker Unified Downlink API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))

# Process state
processes = {
    "scan_livemon": None,
    "imsi_catcher": None,
    "gsm_node": None
}

DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "skytracker_imsis.db"))
PYTHON_PATH = sys.executable
SDR_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(SDR_LOG_DIR, exist_ok=True)

# Keep log file handles alive globally so GC doesn't close them
_open_log_handles = []

def get_process_log_fd(process_name: str):
    """Open a dedicated per-process log file to prevent output interleaving."""
    log_path = os.path.join(SDR_LOG_DIR, f"{process_name}.log")
    fh = open(log_path, "a", buffering=1)  # Line-buffered, never interleaves
    _open_log_handles.append(fh)  # Prevent garbage collection
    return fh

# UI Telemetry Cache (Updated in background to save CPU)
telemetry_data = {
    "status": {},
    "imsis": [],
    "bursts": []
}

async def update_telemetry_loop():
    """Background task to fetch data from DB safely without freezing the SDR."""
    while True:
        try:
            # 1. Update Process Status
            new_status = {}
            for name, proc in processes.items():
                if proc is not None:
                    new_status[name] = "running" if proc.poll() is None else "stopped"
                else:
                    new_status[name] = "stopped"
            telemetry_data["status"] = new_status

            # 2. Fetch DB Data (latest 50 IMSIs and 5 Bursts)
            if os.path.exists(DB_FILE):
                async with aiosqlite.connect(DB_FILE) as db:
                    db.row_factory = aiosqlite.Row
                    
                    cursor = await db.execute("SELECT * FROM observations ORDER BY stamp DESC LIMIT 50")
                    telemetry_data["imsis"] = [dict(row) for row in await cursor.fetchall()]
                    
                    try:
                        cursor = await db.execute("SELECT * FROM rf_bursts ORDER BY timestamp DESC LIMIT 5")
                        telemetry_data["bursts"] = [dict(row) for row in await cursor.fetchall()]
                    except: pass
        except Exception as e:
            print(f"Telemetry loop error: {e}")
        
        await asyncio.sleep(10) # Fixed 10s database query frequency

def check_dependencies():
    """Verify that required system tools are installed."""
    missing = []
    tools = ['grgsm_scanner', 'grgsm_livemon_headless', 'rtl_power', 'mosquitto']
    for tool in tools:
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        raise RuntimeError(f"Missing required system dependencies: {', '.join(missing)}")
    print("All dependencies are successfully verified.")


@app.get("/api/status")
async def get_status():
    """Check the status of the SDR tracking processes."""
    status = {}
    try:
        for name, proc in processes.items():
            if proc is not None:
                try:
                    is_running = proc.poll() is None
                    status[name] = "running" if is_running else "stopped"
                except Exception:
                    status[name] = "error"
            else:
                status[name] = "stopped"
    except Exception as e:
        print(f"Error in /status: {e}")
    return {"status": status}

async def confirm_cleanup():
    """Aggressively ensure no SDR processes are lingering."""
    # 1. Managed process groups
    for name, proc in processes.items():
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except: pass
            processes[name] = None
    
    # 2. Aggressive system-wide nuclear reset (ensures no root-level orphans)
    subprocess.run(["bash", os.path.join(os.path.dirname(__file__), "reset_sdr.sh")], capture_output=True)
    
    await asyncio.sleep(3) # Extra time for USB kernel drivers to release the stick

@app.post("/api/start/imsi")
async def start_imsi_tracking():
    """Start IMSI Catching mode with dynamic tower hopping."""
    await confirm_cleanup()
    
    await asyncio.sleep(1) # Give hardware time to reset

    # 2. Start scan-and-livemon WITH rotation (-r)
    try:
        scan_script = os.path.join(os.path.dirname(__file__), "src/scan-and-livemon.py")
        print(f"Starting Phased Tracking: {scan_script}")
        
        # Each process gets its OWN log file — prevents interleaved output
        log_fh = get_process_log_fd("scan_livemon")
        processes["scan_livemon"] = subprocess.Popen(
            [PYTHON_PATH, "-u", scan_script, "-r"],
            start_new_session=True,
            stdout=log_fh,
            stderr=log_fh
        )
        
        # Immediate health check
        await asyncio.sleep(1)
        if processes["scan_livemon"].poll() is not None:
            raise RuntimeError(f"Scanner died instantly. Check terminal for error.")
            
    except Exception as e:
        print(f"Error starting phased tracker: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # 3. Start simple_IMSI-catcher.py
    try:
        if processes["imsi_catcher"] is None or processes["imsi_catcher"].poll() is not None:
            catcher_script = os.path.join(os.path.dirname(__file__), "src/simple_IMSI-catcher.py")
            print(f"Starting Catcher: {catcher_script}")
            
            # Dedicated log file for the catcher — no interleaving with scanner
            log_fh = get_process_log_fd("imsi_catcher")
            processes["imsi_catcher"] = subprocess.Popen(
                [PYTHON_PATH, "-u", catcher_script, "-a", "-w", DB_FILE],
                start_new_session=True,
                stdout=log_fh,
                stderr=log_fh
            )
            
            # Immediate health check
            await asyncio.sleep(1)
            if processes["imsi_catcher"].poll() is not None:
                print("WARNING: Catcher died instantly. Check permissions.")
    except Exception as e:
        print(f"Error starting catcher: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "SkyTracker Phased Mode started (Scanning -> Hopping active)"}

@app.post("/api/start/node")
async def start_node_tracking():
    """Start GSM Node mode (spectrum scanning)."""
    # 1. Stop IMSI scanner & livemons to free hardware
    if processes["scan_livemon"] is not None and processes["scan_livemon"].poll() is None:
        print("Stopping IMSI scanner/livemon...")
        processes["scan_livemon"].terminate()
        processes["scan_livemon"] = None
    
    # Aggressively clean up any gr-gsm child processes
    subprocess.run(["pkill", "-f", "grgsm_livemon_headless"], capture_output=True)
    await asyncio.sleep(1)

    # 2. Start gsm_node.py
    try:
        if processes["gsm_node"] is None or processes["gsm_node"].poll() is not None:
            node_script = os.path.join(os.path.dirname(__file__), "src/gsm_node.py")
            print(f"Starting gsm_node.py: {node_script}")
            log_fh = get_process_log_fd("gsm_node")
            processes["gsm_node"] = subprocess.Popen(
                [PYTHON_PATH, "-u", node_script],
                start_new_session=True,
                stdout=log_fh,
                stderr=log_fh
            )
    except Exception as e:
        print(f"Error starting GSM Node: {e}")
        raise HTTPException(status_code=500, detail=f"Node failed to start: {e}")

    return {"message": "GSM Node started (IMSI Tracking stopped)"}

@app.post("/api/start")
async def start_tracking():
    """Default start behavior (IMSI tracking)."""
    return await start_imsi_tracking()

@app.post("/api/stop")
async def stop_tracking():
    """Stop all tracking processes cleanly."""
    stopped = []
    
    # Kill managed processes and their entire process groups
    for name, proc in processes.items():
        if proc is not None and proc.poll() is None:
            try:
                # Deep cleanup: kill the whole process group
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                stopped.append(name)
            except Exception as e:
                print(f"Error killing process group {name}: {e}")
                proc.terminate() # Fallback
            processes[name] = None
    
    # Aggressive cleanup of any remaining orphaned subprocesses
    subprocess.run(["pkill", "-9", "-f", "grgsm_livemon_headless"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "grgsm_scanner"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "rtl_power"], capture_output=True)
    
    await asyncio.sleep(2) # Cooldown to release hardware

@app.get("/api/data/imsis")
async def get_imsis(limit: int = 100):
    """Retrieve the latest IMSIs caught."""
    if not os.path.exists(DB_FILE):
        return {"imsis": []}

    try:
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM observations ORDER BY stamp DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
            # Convert rows to dict
            return {"imsis": [dict(row) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data/bursts")
async def get_bursts(limit: int = 10):
    """Retrieve the latest RF energy bursts detected by the GSM node."""
    if not os.path.exists(DB_FILE):
        return {"bursts": []}

    try:
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM rf_bursts ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
            return {"bursts": [dict(row) for row in rows]}
    except Exception as e:
        # If table doesn't exist yet, just return empty list
        if "no such table" in str(e).lower():
            return {"bursts": []}
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/refresh")
async def get_refresh():
    """Ultra-fast endpoint serving the background-cached telemetry snapshot."""
    return telemetry_data

@app.post("/api/update-codes")
async def update_mcc_codes(background_tasks: BackgroundTasks):
    """Trigger an asynchronous update of MCC/MNC codes."""
    def run_update():
        subprocess.run(["python3", "src/update_codes.py"])
    background_tasks.add_task(run_update)
    return {"message": "Update codes task started in background."}

@app.get("/api/logs")
async def get_sdr_logs(lines: int = 50):
    """Return the last N lines across all per-process SDR log files."""
    all_logs = []
    for name in ["scan_livemon", "imsi_catcher", "gsm_node"]:
        log_path = os.path.join(SDR_LOG_DIR, f"{name}.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    all_logs.extend([f"[{name}] {l.rstrip()}" for l in f.readlines()])
            except Exception:
                continue
    return {"logs": all_logs[-lines:]}

@app.get("/api/debug")
async def debug():
    """Diagnostic route to confirm API is handling /api/ prefix."""
    return {
        "status": "alive",
        "prefix": "/api",
        "mount_point": DASHBOARD_DIR
    }

@app.get("/api/health")
async def health():
    """Simple API health check."""
    return {"status": "ok", "api": "active"}

@app.get("/api/ping")
async def ping():
    """Simple health check for the API."""
    return {"ping": "pong"}

# ---- Inline SVG Favicon (no external file needed) ----
FAVICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="45" fill="#1e1e1e" stroke="#4a90e2" stroke-width="3"/>
  <path d="M50 15 L50 50 L75 60" stroke="#4a90e2" stroke-width="4" fill="none" stroke-linecap="round"/>
  <circle cx="50" cy="50" r="5" fill="#e74c3c"/>
  <circle cx="50" cy="25" r="3" fill="#4a90e2" opacity="0.6"/>
  <circle cx="72" cy="38" r="3" fill="#4a90e2" opacity="0.6"/>
  <circle cx="72" cy="62" r="3" fill="#4a90e2" opacity="0.6"/>
  <circle cx="50" cy="75" r="3" fill="#4a90e2" opacity="0.6"/>
  <circle cx="28" cy="62" r="3" fill="#4a90e2" opacity="0.6"/>
  <circle cx="28" cy="38" r="3" fill="#4a90e2" opacity="0.6"/>
</svg>'''

@app.get("/favicon.ico")
async def favicon():
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")

if os.path.exists(DASHBOARD_DIR):
    @app.get("/")
    async def serve_dashboard():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_static(path: str):
        # Prevent accessing API routes via this handler
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
            
        file_path = os.path.join(DASHBOARD_DIR, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
            
        # Fallback to index for SPA-like behavior or just 404
        raise HTTPException(status_code=404)
else:
    print(f"Warning: Dashboard directory not found at {DASHBOARD_DIR}")

if __name__ == "__main__":
    # Apply the log filter to suppress /api/refresh spam
    logging.getLogger("uvicorn.access").addFilter(RefreshLogFilter())
    uvicorn.run(app, host="0.0.0.0", port=8000)
