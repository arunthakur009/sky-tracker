#!/bin/bash
# Description: Configures the Raspberry Pi as a standalone Wi-Fi Access Point using NetworkManager.
# SSID: SKYTRACKER_LINK
# Password: rescueadmin
# IP Address: 192.168.4.1

set -e

echo "Creating SKYTRACKER_LINK hotspot via NetworkManager..."

# Check if a connection with the same name already exists and delete it
if nmcli con show "skytracker_ap" > /dev/null 2>&1; then
    echo "Removing existing skytracker_ap connection..."
    nmcli con delete "skytracker_ap"
fi

# Create a new Wi-Fi hotspot
nmcli con add type wifi ifname wlan0 con-name skytracker_ap autoconnect yes ssid SKYTRACKER_LINK
nmcli con modify skytracker_ap 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv4.addresses 192.168.4.1/24
nmcli con modify skytracker_ap wifi-sec.key-mgmt wpa-psk wifi-sec.psk "rescueadmin"

# Bring up the interface
nmcli con up skytracker_ap

echo "Access Point setup complete."
