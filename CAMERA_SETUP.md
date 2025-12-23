# Camera Streaming Setup Guide

## Setup Instructions for Raspberry Pi 5 + Camera Module 3

### Step 1: Stop qcam (IMPORTANT!)
The camera can only be used by ONE application at a time. You must close qcam before running the server:

```bash
# Kill any running qcam instances
pkill -f qcam

# Or press Ctrl+C in the terminal running qcam
```

### Step 2: Install Dependencies
```bash
# Install picamera2 (if not already installed)
sudo apt update
sudo apt install -y python3-picamera2

# Install Python dependencies
pip3 install websockets asyncio lgpio aiohttp pillow
```

### Step 3: Configure Camera
```bash
# Run Raspberry Pi configuration
sudo raspi-config

# Navigate to:
# 3. Interface Options
# > I1 Legacy Camera
# > Select "No" (Disable legacy camera)
# > Finish and reboot if prompted
```

### Step 4: Start the Server
```bash
cd /path/to/your/project
python3 raspberry-pi-server.py
```

You should see:
```
✅ Camera initialized successfully (1280x720, JPEG quality 85)
   Camera Module 3 detected and configured
📹 HTTP Camera Server started on port 8080
```

### Step 5: Configure the App

1. **Get your Raspberry Pi's IP address:**
   ```bash
   hostname -I
   ```
   Example output: `192.168.1.100`

2. **Open the app on your phone**

3. **Tap the Settings button** (gear icon)

4. **Enter your Pi's IP address:**
   - Just the IP: `192.168.1.100`
   - **Don't add** http://, ws://, or port numbers
   - The app automatically handles ports (8765 for WebSocket, 8080 for camera)

5. **Tap "SAVE & CONNECT"**

6. **You should see:**
   - Status: "CONNECTED" (green)
   - Camera stream appears automatically

### Troubleshooting

#### Camera Not Working?

**Error: "Resource busy" or "Camera in use"**
```bash
# Check what's using the camera
fuser /dev/video0

# Kill all camera processes
pkill -f qcam
pkill -f libcamera
```

**Camera not detected:**
```bash
# List cameras
libcamera-hello --list-cameras

# If you see your camera, the hardware is working
# Reboot your Pi:
sudo reboot
```

**Still not working?**
1. Make sure camera ribbon cable is properly connected
2. Check camera is enabled: `sudo raspi-config` → Interface Options → Camera → Enable
3. Try disabling legacy camera (see Step 3 above)
4. Reboot after any configuration changes

#### App Not Connecting?

**Both devices must be on the same WiFi network!**

```bash
# On Raspberry Pi, verify IP:
hostname -I

# Test camera stream in browser on your phone:
http://192.168.1.100:8080/
# (Replace with your Pi's IP)
```

**Firewall issues?**
```bash
# Temporarily disable firewall to test
sudo ufw disable

# If it works, open ports:
sudo ufw allow 8765/tcp  # WebSocket
sudo ufw allow 8080/tcp  # Camera
sudo ufw enable
```

### Testing Camera Stream in Browser

Open this URL in any browser on your phone (same WiFi):
```
http://YOUR_PI_IP:8080/?action=stream
```

Example: `http://192.168.1.100:8080/?action=stream`

You should see the live camera feed. If this works but the app doesn't, the issue is with WebSocket connection, not the camera.

### Remote Access (Optional)

To access from anywhere using ngrok:

1. **Install ngrok:**
   ```bash
   curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
   echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
   sudo apt update && sudo apt install ngrok
   
   # Sign up at https://ngrok.com and get your auth token
   ngrok config add-authtoken YOUR_TOKEN
   ```

2. **Run ngrok:**
   ```bash
   ngrok http 8765 --host-header=rewrite
   ```

3. **Copy the hostname** from the "Forwarding" line:
   ```
   Forwarding https://abc123.ngrok-free.app -> http://localhost:8765
   ```
   Copy: `abc123.ngrok-free.app`

4. **Enter in app settings** (just the hostname, no https://)

**Note:** Camera streaming over ngrok may be slow due to bandwidth. Works best on local network.

## Quick Reference

| Component | Port | URL Format |
|-----------|------|------------|
| WebSocket | 8765 | `ws://IP:8765` |
| Camera HTTP | 8080 | `http://IP:8080/?action=stream` |
| Browser Test | 8080 | `http://IP:8080/` |

## Common Commands

```bash
# Start server
python3 raspberry-pi-server.py

# Stop server
Ctrl+C

# Check Pi IP
hostname -I

# Test camera
libcamera-hello --list-cameras

# Kill camera apps
pkill -f qcam

# View server logs
# All logs appear in the terminal where you run the script
```
