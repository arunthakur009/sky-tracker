#!/bin/bash
# Nuclear SDR Reset Script for SkyTracker

# Restore terminal formatting (fixes staircase text)
stty sane 2>/dev/null || true

echo "[*] Performing Nuclear SDR Reset..."

# 1. Kill all potential SDR and catcher processes (no sudo; we own them)
pkill -9 -f grgsm_scanner 2>/dev/null
pkill -9 -f grgsm_livemon_headless 2>/dev/null
pkill -9 -f simple_IMSI-catcher.py 2>/dev/null
pkill -9 -f scan-and-livemon.py 2>/dev/null
pkill -9 -f gsm_node.py 2>/dev/null
pkill -9 -f rtl_power 2>/dev/null
pkill -9 -f rtl_sdr 2>/dev/null
pkill -9 -f rtl_test 2>/dev/null

# 2. Force-clear the SDR data ports (fuser doesn't need sudo for user-owned sockets)
fuser -k 4729/udp 2>/dev/null || true
fuser -k 4733/udp 2>/dev/null || true

echo "[*] SDR Reset Complete. Hardware should be free."
sleep 1
