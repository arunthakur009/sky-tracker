# SkyTracker Downlink Workflow

Welcome to the **SkyTracker Downlink** system. This system is designed to run efficiently on a Raspberry Pi, allowing you to interface with RTL-SDR hardware to capture GSM packet data, identify frequencies with heavy network traffic, and read IMSI / TMSI information.

Previously, these operations required multiple scripts and terminals. We have unified the deployment into a single REST API `api.py`.

## Features
- **One-Command Start**: Spin up `scan-and-livemon`, `simple_IMSI-catcher`, and `gsm_node` with a single API request.
- **Dependency Checks**: The API automatically checks for `grgsm_scanner`, `grgsm_livemon_headless`, `rtl_power`, and `mosquitto` at startup.
- **Zombie Process Cleaning**: Clean shutdown of `rtl_power` and `livemon` processes without leaving orphaned instances running.
- **SQLite Data Integrity**: Data is saved to `skytracker_imsis.db` and is easy to query.
- **Unified Endpoints**: Get IMSI catches or restart the node instantly using HTTP.

## Workflow File Structure

- `api.py`: The main FastAPI server that orchestrates everything. **THIS IS THE ONLY SCRIPT YOU NEED TO RUN MANUALLY**.
- `src/scan-and-livemon`: Scans RF frequencies for strong base stations and automatically starts `grgsm_livemon_headless` loopback instances starting at UDP port `4729`.
- `src/simple_IMSI-catcher.py`: Sniffs loopback packets (ports `4729-4740`), extracts IMSI and TMSI data from the GSMP headers, correlates them with MCC brands, and logs them to SQLite.
- `src/gsm_node.py`: Sweeps the 900MHz band to detect active transmission spikes. Posts the telemetry to a local Mosquitto MQTT broker on the `skytracker/gsm` topic.
- `src/update_codes.py`: Scrapes Wikipedia to update `mcc_codes.json` for mapping network IDs to carrier names.
- `skytracker_imsis.db`: SQLite database that holds historical IMSI catches (generated automatically upon start).

## Installation & Requirements

Ensure that you have all the required Linux SDR dependencies installed on the Pi:
```bash
sudo apt update
sudo apt install gr-gsm rtl-sdr mosquitto
```
Next, install the Python requirements:
```bash
pip install -r requirements.txt
```

## Running the API

Start up the unified API interface (`uvicorn` will run on port `8000`):

```bash
sudo python3 api.py
```
*(Running with `sudo` may be required if scapy needs raw packet sniffing for the IMSI catcher).*

## API Endpoints

Once running, you can connect from any web client or terminal to control the system:

### 1. `GET /status`
Check if the sub-processes are running.
```bash
curl http://localhost:8000/status
```
Response:
```json
{
  "status": {
    "scan_livemon": "stopped",
    "imsi_catcher": "stopped",
    "gsm_node": "stopped"
  }
}
```

### 2. `POST /start`
Kick off the entire SDR workflow.
```bash
curl -X POST http://localhost:8000/start
```

### 3. `GET /data/imsis?limit=100`
Get the latest 100 IMSI intercepts. This parses the local SQLite directly.
```bash
curl http://localhost:8000/data/imsis
```

### 4. `POST /stop`
Gracefully kill all tracking processes and cleanup SDR hardware locks.
```bash
curl -X POST http://localhost:8000/stop
```

### 5. `POST /update-codes`
Runs an asynchronous scrape to refresh Mobile Country Codes in `mcc_codes.json`.
```bash
curl -X POST http://localhost:8000/update-codes
```
