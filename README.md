Setup

How to setup meshtastic device guide: https://www.youtube.com/watch?v=OoxD5pSbibk
Meshtastic Flasher: https://flasher.meshtastic.org/
*Remember to set the region to Singapore (SG_923/Singapore 923MHz)

Raspberry PI 0 setup:

Raspberry Pi Zero setup: https://xsite.singaporetech.edu.sg/d2l/le/content/110228/viewContent/612624/View 
*For OS use raspberry pi 32bit bookworm
https://meshtastic.org/docs/hardware/devices/linux-native-hardware/?os=raspbian 

Steps(After install raspberry pi zero os (fresh install)):

1.Install Required Packages:
sudo apt update
sudo apt install python3-full python3-pip python3-venv bluetooth bluez
2.Set up Project and Virtual Environment:
mkdir ~/meshtastic_project
cd ~/meshtastic_project
python3 -m venv venv
source venv/bin/activate
pip3 install meshtastic
pip3 install bluepy
For rpi 4 if encounter error to install bluepy: sudo apt install -y libglib2.0-dev libdbus-1-dev libudev-dev  
3.Enable Bluetooth:
# Edit Bluetooth configuration
sudo nano /etc/bluetooth/main.conf
# Add or modify these lines:
DiscoverableTimeout = 0
Discoverable = true
# Restart Bluetooth
sudo usermod -a -G bluetooth pi
sudo systemctl restart bluetooth
6.Service Setup:
sudo nano /etc/systemd/system/meshtastic.service
Paste this:
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
7.Enable and Start Service:
sudo systemctl daemon-reload
sudo systemctl enable meshtastic.service
sudo systemctl start meshtastic.service
bluetoothctl
scan on
Note: wait for the scan and you should find your meshtasic device mac-address and bluetooth id:
# Wait for Meshtastic device to appear (note the MAC address)
pair XX:XX:XX:XX:XX:XX (if there is a need for bluetooth pin it will prompt for it default bluetooth pin:123456)
trust XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX
*To stop scanning for bluetooth devices type: scan off

# Wait for Meshtastic device to appear (note the MAC address)
pair XX:XX:XX:XX:XX:XX (if there is a need for bluetooth pin it will prompt for it default bluetooth pin:123456)
trust XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX
*To stop scanning for bluetooth devices type: scan off
*Use this to see which bluetooth devices is connected: devices

Add additional wifi connection(optional):
Open a terminal and run:

sudo nmtui
Select "Edit a connection" and press Enter.
Use arrow keys to select the Wi-Fi connection you want to modify.
Press Enter, then look for "Add".
Enter the information 
Press OK and then Back.
Restart NetworkManager for changes to take effect:

sudo systemctl restart NetworkManager
Add priority to wifi connection(optional):
List available Wi-Fi connections:
pgsql
CopyEdit
nmcli connection show
Example output:
pgsql
CopyEdit
NAME            UUID                                  TYPE      DEVICE 
HomeWiFi       12345-6789-ABCD-EF01-23456789ABCD    wifi      wlan0  
OfficeWiFi     ABCD-1234-5678-90EF-ABCDEF123456    wifi      --

Set priority for a Wi-Fi network:

sudo nmcli connection modify "HomeWiFi" connection.autoconnect-priority 100
sudo nmcli connection modify "OfficeWiFi" connection.autoconnect-priority 50

The network with the higher priority value (e.g., 100) will be preferred.
Default priority is usually 0, so setting a higher number makes it more preferred.
Apply changes by restarting NetworkManager:

sudo systemctl restart NetworkManager

Verify the changes:

nmcli connection show "HomeWiFi" | grep priority

Expected output:
connection.priority: 100

Raspberry PI 0 OS image cloning:
After setting up the raspberry pi, you can clone the raspberry pi image to the other sd card by using the following tools(*Note: This would not work if the image you are trying to clone overall storage size is bigger than the sd card you are trying to clone to):
https://win32diskimager.org/ (Preferable)
https://etcher.balena.io/#download-etcher 
Guide for both on how to use:
https://www.youtube.com/watch?v=jeBMu4whqqE
https://www.youtube.com/watch?v=Pyvf43Lw-Io 

Remember to change the hostname: https://www.redhat.com/en/blog/configure-hostname-linux 

Meshtastic Setup:

Setup LoRA between meshtastic
Meshtastic 1:
meshtastic --ch-index 0 --ch-set name Message
meshtastic --ch-index 0 --ch-longfast
meshtastic --ch-index 0 --ch-set psk random
 *channel 0 is also known as primary channel
Meshtastic 2:
meshtastic --seturl “Replace this with primary channel URL of meshtastic 1”
Test:
meshtastic --nodes (ensure the node is associated)
meshtastic --sendtext "Test message"





