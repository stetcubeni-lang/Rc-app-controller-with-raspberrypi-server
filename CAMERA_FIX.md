# Camera Streaming Fix Guide

## Problem
The camera stream fails because:
1. `qcam` or other apps are using the camera, locking it
2. Only ONE app can access the Pi Camera at a time
3. The Python server needs exclusive camera access

## Solution

### Step 1: Stop All Camera Apps
On your Raspberry Pi, run:
```bash
# Stop qcam if running
pkill -f qcam

# Stop other camera apps
pkill libcamera-hello
pkill rpicam-hello
pkill rpicam-vid
```

### Step 2: Verify Camera is Detected
```bash
libcamera-hello --list-cameras
```

You should see output like:
```
Available cameras
-----------------
0 : imx708 [4608x2592] (/base/axi/pcie@120000/rp1/i2c@88000/imx708@1a)
```

If you don't see the camera:
```bash
# Enable camera in raspi-config
sudo raspi-config
# Navigate to: Interface Options -> Camera -> Enable

# Reboot
sudo reboot
```

### Step 3: Install Required Packages
```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-libcamera python3-kms++ python3-prctl libatlas-base-dev ffmpeg
```

### Step 4: Start the Python Server
```bash
cd /path/to/your/project
python3 raspberry-pi-server.py
```

The server will:
- Automatically stop qcam/other camera apps if running
- Initialize the Camera Module 3
- Start streaming on port 8080
- Show you the connection URLs

### Step 5: Configure App Settings

#### For Local Network (Same WiFi):
1. Look at the server output for "Local Network IP"
2. Copy just the IP (e.g., `192.168.31.103`)
3. Paste in app settings

#### For Remote Access (ngrok):
1. Look at the server output for ngrok URL
2. Copy ONLY the hostname (e.g., `joline-unfauceted-zayne.ngrok-free.dev`)
3. NO `https://`, NO `wss://`, NO port number
4. Paste in app settings

### Step 6: Verify Camera Stream

#### Check in Browser:
Open browser on any device on the same network:
```
http://192.168.31.103:8080/
```

You should see:
- "Camera Status: ✅ Active (Pi Camera Module 3)"
- Live camera stream

#### Check in Terminal:
Server logs should show:
```
✅ Camera initialized successfully (1280x720 @ 10Mbps MJPEG)
✅ Pi Camera Module 3 ready for streaming
```

## Troubleshooting

### Camera Still Not Working?

1. **Check what's using the camera:**
   ```bash
   sudo fuser -v /dev/video0
   ```

2. **Force kill all camera processes:**
   ```bash
   sudo pkill -9 -f "qcam|libcamera|rpicam"
   ```

3. **Check camera hardware:**
   ```bash
   vcgencmd get_camera
   ```
   Should show: `supported=1 detected=1`

4. **Check permissions:**
   ```bash
   groups
   ```
   Make sure you're in the `video` group. If not:
   ```bash
   sudo usermod -a -G video $USER
   # Logout and login again
   ```

5. **Reboot if all else fails:**
   ```bash
   sudo reboot
   ```

### WebSocket Connection Issues?

1. **Local Network:**
   - Make sure both devices on same WiFi
   - Check firewall: `sudo ufw status`
   - Test connection: `ping 192.168.31.103`

2. **ngrok:**
   - Make sure ngrok is running: `ps aux | grep ngrok`
   - Check ngrok status: `curl http://localhost:4040/api/tunnels`
   - Restart ngrok if needed:
     ```bash
     pkill ngrok
     ngrok http 8765 --host-header=rewrite
     ```

## Important Notes

⚠️ **DO NOT run qcam while the Python server is running!**
- Only ONE app can use the camera at a time
- The Python server needs exclusive access
- If you want to test with qcam, stop the Python server first

⚠️ **Camera via ngrok:**
- Camera stream (port 8080) is NOT tunneled by ngrok by default
- Only WebSocket controls (port 8765) work remotely via ngrok
- For remote camera access, you need TWO ngrok tunnels:
  ```bash
  # Terminal 1: WebSocket
  ngrok http 8765 --host-header=rewrite
  
  # Terminal 2: Camera (requires paid ngrok plan for multiple tunnels)
  ngrok http 8080
  ```

✅ **Best Setup:**
- Use **same WiFi** for full functionality (controls + camera)
- Use **ngrok** only for remote control when camera view is not critical
