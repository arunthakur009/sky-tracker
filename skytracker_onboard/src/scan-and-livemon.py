#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Description:
# Scans for local GSM base stations and attaches grgsm_livemon_headless
# to the strongest frequencies found. The captured packets are then
# forwarded to the local loopback interface for downstream processing.

import importlib.util
import importlib.machinery
from optparse import OptionParser
import subprocess
import sys
import os
import shutil
import socket
import time

def import_module_from_path(module_name, file_path):
    """Dynamically loads a python module from a given file path."""
    source_loader = importlib.machinery.SourceFileLoader(module_name, file_path)
    module_spec = importlib.util.spec_from_file_location(module_name, file_path, loader=source_loader)
    loaded_module = importlib.util.module_from_spec(module_spec)
    source_loader.exec_module(loaded_module)
    return loaded_module

def discover_gsm_frequencies():
    """Locates the grgsm_scanner executable and runs a scan to find base stations."""
    try:
        # Load our patched local copy of grgsm_scanner
        local_scanner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grgsm_scanner_local.py")
        print(f"[*] Importing patched scanner module from {local_scanner}")
        scanner_module = import_module_from_path('scanner', local_scanner)
        sys.modules['scanner'] = scanner_module
        
        # Monkey-patch gr-osmosdr API breaking change for newer gnuradio
        import gnuradio.gsm.device as gsm_device
        gsm_device.get_default_args = lambda hint="": "rtl=0"
    except Exception as e:
        print(f"CRITICAL: Failed to load local scanner: {e}")
        sys.exit(1)
    
    # Parse args from the scanner module, passing empty list to avoid parsing sys.argv (like -n)
    (opts, args) = scanner_module.argument_parser().parse_args(args=[])
    
    # 1. Primary Scan (GSM900) - Wide European/Asian standard
    opts.band = "GSM900"
    opts.gain = 34.0
    opts.samp_rate = 2000000 # Required by grgsm_scanner
    
    print(f"[*] Starting primary scan [{opts.band}] (Gain: {opts.gain}dB)...")

    found_stations = scanner_module.do_scan(
        opts.samp_rate, opts.band, opts.speed,
        opts.ppm, opts.gain, opts.args, debug=True
    )
    
    if not found_stations:
        print("[!] No GSM900 stations found. Falling back to DCS1800 (High-band)...")
        opts.band = "DCS1800"
        found_stations = scanner_module.do_scan(
            opts.samp_rate, opts.band, opts.speed,
            opts.ppm, opts.gain, opts.args, debug=True
        )
        
    return found_stations

def pick_best_frequencies(stations, target_count=1):
    """
    Sorts stations by power and operator diversity and returns a list 
    of the best frequencies.
    """
    candidates = list(stations)
    # Sort highest power first, grouping by MCC/MNC
    candidates.sort(key=lambda s: (-s.power, s.mcc, s.mnc))

    selected_freqs = []
    for station in candidates:
        if target_count > 0:
            selected_freqs.append(station.freq)
            target_count -= 1
        else:
            break

    return selected_freqs

def setup_cli():
    parser = OptionParser(usage="%prog: [options]")
    parser.add_option("-n", "--numrecv", dest="numreceivers", type="int",
        default=1,
        help="Number of background livemon processes to spawn [default=%default]")
    parser.add_option("-r", "--rotate", dest="rotate", action="store_true",
        default=False,
        help="Enable frequency rotation (hops every 3 minutes) [default=%default]")
    return parser

def is_port_busy(port):
    """Check if a network port is currently being used."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def force_clear_port(port):
    """Aggressively kill any process holding the specified port."""
    try:
        # Use lsof to find the PID and kill it forcefully
        cmd = f"lsof -t -i:{port} | xargs kill -9"
        subprocess.run(cmd, shell=True, capture_output=True)
        time.sleep(1) # Give OS time to recycle
    except Exception:
        pass

def execute_monitor_workflow(opts=None):
    if opts is None:
        (opts, _) = setup_cli().parse_args()

    # Bulletproof port clearing for the scanner's reporting port (4733)
    print(f"[*] Preparing radio resources (Clearing port 4733)...")
    force_clear_port(4733)
    
    # Final check
    if is_port_busy(4733):
        print("CRITICAL: Could not clear port 4733. Scanner may fail.")
    stations = discover_gsm_frequencies()
    print(f"[*] Sweep complete. Found {len(stations)} active frequencies.")
    
    if len(stations) > 0:
        # Pick top 3 for rotation or just top N requested
        limit = 3 if opts.rotate else opts.numreceivers
        freqs_to_monitor = pick_best_frequencies(stations, limit)

        if not opts.rotate:
            print(f"[*] Attaching to {len(freqs_to_monitor)} strongest GSM base stations.")
            process_pool = []
            base_port = 4733
            for freq in freqs_to_monitor:
                print(f" -> Launching optimized livemon on {freq} Hz | Port: {base_port}")
                cmd = ["grgsm_livemon_headless", "-s", "1000000", f"--serverport={base_port}", f"--args=rtl=0", f"--gain=15", "-f", str(freq)]
                process_pool.append(subprocess.Popen(cmd))
                base_port += 1
            try:
                for p in process_pool: p.wait()
            except KeyboardInterrupt:
                for p in process_pool: p.terminate()
        else:
            print(f"[*] Dynamic Tower Hopping enabled. Rotating between {len(freqs_to_monitor)} frequencies.")
            import time
            current_idx = 0
            while True:
                freq = freqs_to_monitor[current_idx]
                print(f"\n[*] [HOpping] Switching to Tower: {freq} Hz (Standard 1.0M Rate)")
                cmd = ["grgsm_livemon_headless", "-s", "1000000", "--serverport=4733", "--args=rtl=0", "--gain=15", "-f", str(freq)]
                
                proc = subprocess.Popen(cmd)
                try:
                    # Wait for 3 minutes (180 seconds)
                    time.sleep(180)
                    print(f"[*] Hop interval reached. Switching...")
                    proc.terminate()
                    proc.wait()
                    current_idx = (current_idx + 1) % len(freqs_to_monitor)
                except KeyboardInterrupt:
                    print("\n[*] Stopping rotation...")
                    proc.terminate()
                    break

if __name__ == '__main__':
    execute_monitor_workflow()
