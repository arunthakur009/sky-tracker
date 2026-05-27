# sky-tracker
Collecting workspace information# sky-tracker

A comprehensive GSM network monitoring and tracking system with web dashboard and onboard SDR (Software Defined Radio) capabilities.

## Project Structure

- **skytracker_onboard/** - Main application directory
  - `api.py` - REST API server
  - `src/` - Core application modules
  - `logs/` - Application log files
  - `systemd/` - Systemd service configuration
- **web_dashboard/** - Web interface for monitoring
  - `index.html` - Dashboard UI
  - `script.js` - Frontend logic
  - `style.css` - Styling
- **skytracker_imsis.db** - SQLite database for storing IMSI data

## Features

- GSM network scanning and monitoring
- IMSI catcher detection and logging
- Live packet capture and analysis
- RESTful API for data access
- Web-based dashboard for visualization
- SDR integration for signal processing
- Systemd service integration

## Installation

1. Install dependencies:
```bash
cd skytracker_onboard
pip install -r requirements.txt
```

2. Run setup scripts:
```bash
./setup_ap.sh      # Configure access point
./reset_sdr.sh     # Reset SDR hardware
```

3. Start the application:
```bash
./start.sh
```

## Configuration

- Edit api.py for API configuration
- Modify src modules for scanning parameters
- Update web_dashboard for dashboard customization

## Usage

Access the web dashboard at `http://localhost:8000` (default) and monitor:
- GSM network parameters
- Detected IMSI values
- Signal strength readings
- Network events and alerts

## License

See README.md in the skytracker_onboard directory for additional details.
