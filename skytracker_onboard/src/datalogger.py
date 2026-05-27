"""
datalogger.py
description: Drone black box logger. Subscribes to 'skytracker/#' and saves JSON payloads
to a local JSON Lines (JSONL) file.
"""

import os
import time
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt

# Configuration
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
SUBSCRIBE_TOPIC = "skytracker/#"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("datalogger")

class DataLogger:
    def __init__(self):
        # Create log directory if it doesn't exist
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)
            logger.info(f"Created log directory at {LOG_DIR}")
            
        # Dynamically generate log filename based on startup time
        start_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_filename = os.path.join(LOG_DIR, f"flightlog_{start_time_str}.jsonl")
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="skytracker_logger")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            client.subscribe(SUBSCRIBE_TOPIC, qos=1)
            logger.info(f"Subscribed to topic: {SUBSCRIBE_TOPIC}")
        else:
            logger.error(f"Failed to connect, return code: {reason_code}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("Disconnected from MQTT broker. Reconnecting...")

    def on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode('utf-8')
            payload_data = json.loads(payload_str)
            
            # Inject origin topic into the payload
            payload_data["_topic"] = msg.topic
            
            # Save to JSONL
            with open(self.log_filename, "a") as f:
                f.write(json.dumps(payload_data) + "\n")
                
            logger.debug(f"Logged message from {msg.topic}")
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON payload on topic {msg.topic}: {msg.payload}")
        except Exception as e:
            logger.error(f"Error handling message on {msg.topic}: {e}")

    def start(self):
        logger.info(f"Starting DataLogger. Logging to: {self.log_filename}")
        
        while True:
            try:
                self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                break
            except ConnectionRefusedError:
                logger.error("MQTT Broker connection refused. Retrying in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"MQTT Broker connection error: {e}. Retrying in 5 seconds...")
                time.sleep(5)
                
        self.client.loop_start()

    def stop(self):
        logger.info("Stopping DataLogger...")
        self.client.loop_stop()
        self.client.disconnect()

if __name__ == "__main__":
    datalogger = DataLogger()
    try:
        datalogger.start()
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        datalogger.stop()
