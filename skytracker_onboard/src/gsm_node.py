"""
gsm_node.py
description: SDR data collection node for the SKYTRACKER system.
Connects to local Mosquitto MQTT broker, simulates gr-gsm/kalibrate-rtl SDR output,
and publishes data to 'skytracker/gsm'.
"""

import time
import json
import random
import logging
import subprocess
import csv
import io
import sqlite3
import datetime
import paho.mqtt.client as mqtt

# Configuration
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "skytracker/gsm"
POLL_INTERVAL = 5.0

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("gsm_node")

DB_FILE = "skytracker_imsis.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rf_bursts("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "timestamp DATETIME,"
        "frequency REAL,"
        "rssi REAL"
        ");"
    )
    conn.commit()
    conn.close()

def log_burst_to_db(freq, rssi):
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "INSERT INTO rf_bursts (timestamp, frequency, rssi) VALUES (?, ?, ?)",
            (datetime.datetime.now().isoformat(), freq, rssi)
        )
        conn.commit()
        conn.close()
        print(f"[*] Successfully logged RF Burst to SQLite: {freq} MHz | RSSI: {rssi}")
    except Exception as e:
        logger.error(f"Failed to log burst to DB: {e}")

def get_sdr_data():
    """
    Uses rtl_power to scan the GSM-900 Uplink band (890MHz - 915MHz)
    looking for RF energy spikes (phones trying to connect).
    """
    # rtl_power command: 
    # -f 890M:915M:1M (Scan 890-915MHz in 1MHz buckets)
    # -i 2 (Integrate for 2 seconds)
    # -1 (Run once and exit)
    command = ["rtl_power", "-f", "890M:915M:1M", "-i", "2", "-1"]
    
    try:
        # Run the command and capture the output
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            logger.error(f"SDR Error: {result.stderr}")
            return None

        # rtl_power outputs raw CSV data to stdout. We need to parse it.
        # Format: date, time, Hz low, Hz high, Hz step, samples, dbm, dbm, dbm...
        csv_data = io.StringIO(result.stdout)
        reader = csv.reader(csv_data)
        
        highest_rssi = -100.0 # Start with a very low baseline noise floor
        active_freq = 0.0
        
        for row in reader:
            if not row: continue
            
            freq_low = float(row[2])
            freq_step = float(row[4])
            
            # The dBm values start at index 6
            dbm_values = [float(x) for x in row[6:] if x.strip() != '']
            
            for i, dbm in enumerate(dbm_values):
                if dbm > highest_rssi:
                    highest_rssi = dbm
                    active_freq = freq_low + (i * freq_step)

        # Threshold: If the strongest signal is below -60dBm, it's just background noise.
        # If it's above -60dBm, it's likely a device transmitting.
        if highest_rssi > -60.0:
             freq_mhz = round(active_freq / 1000000, 2)
             log_burst_to_db(freq_mhz, round(highest_rssi, 2))
             return {
                "device_id": "UNKNOWN_UPLINK_DEVICE", # We can't read IMSI passively
                "frequency": freq_mhz,
                "rssi": round(highest_rssi, 2)
            }
        else:
            return None # No active phones detected in this sweep

    except subprocess.TimeoutExpired:
        logger.error("SDR Scanner timed out.")
        return None
    except Exception as e:
        logger.error(f"Error reading SDR: {e}")
        return None

def on_connect(client, userdata, flags, reason_code, properties):
    """Callback triggered on MQTT connection."""
    if reason_code == 0:
        logger.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        logger.error(f"Failed to connect to MQTT broker, return code {reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    """Callback triggered on MQTT disconnection."""
    logger.warning("Disconnected from MQTT broker. Reconnecting...")

def main():
    logger.info("Initializing SKYTRACKER GSM Node...")
    init_db()
    
    # Initialize MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="skytracker_gsm_node")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    
    # Attempt connection with robust retry
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except ConnectionRefusedError:
            logger.error("MQTT Broker connection refused. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"MQTT Broker connection error: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            
    client.loop_start()
    
    try:
        while True:
            # Poll SDR data
            sdr_data = get_sdr_data()
            
            if sdr_data:
                # Timestamp (No GPS, relying on system time)
                sdr_data["timestamp"] = time.time()
                
                payload_str = json.dumps(sdr_data)
                
                # Publish payload
                client.publish(MQTT_TOPIC, payload_str, qos=1)
                logger.info(f"Published to {MQTT_TOPIC}: {payload_str}")
            
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down GSM Node...")
    except Exception as e:
        logger.error(f"Unexpected error in GSM Node loop: {e}", exc_info=True)
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("GSM Node shutdown complete.")

if __name__ == "__main__":
    main()
