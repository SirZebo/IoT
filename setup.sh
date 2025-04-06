#!/bin/bash

sudo apt update
sudo apt install python3-full python3-pip python3-venv bluetooth bluez
mkdir ~/meshtastic_project
cd ~/meshtastic_project
python3 -m venv venv
source venv/bin/activate
pip3 install meshtastic
pip3 install bluepy

sudo tee -a /etc/bluetooth/main.conf <<EOF
# Add or modify these lines:
DiscoverableTimeout = 0
Discoverable = true
EOF

sudo usermod -a -G bluetooth pi
sudo systemctl restart Bluetooth

sudo tee -a /etc/systemd/system/meshtastic.service <<EOF
[Unit]
Description=Meshtastic BLE Communication Service
After=bluetooth.service

[Service]
ExecStart=/home/pi/meshtastic_project/venv/bin/python3 /home/pi/meshtastic_project/mesh_ble_communication.py
Environment=PATH=/home/pi/meshtastic_project/venv/bin:$PATH
WorkingDirectory=/home/pi/meshtastic_project
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable meshtastic.service
sudo systemctl start meshtastic.service


