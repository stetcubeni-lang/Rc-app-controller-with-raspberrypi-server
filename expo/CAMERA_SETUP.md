# 📹 Raspberry Pi Camera Module 3 Setup Guide

## Quick Start

### Step 1: Stop Other Camera Applications

The camera can only be used by one application at a time. If you're using `libcamera-hello`, `rpicam-hello`, or any other camera app, stop them first:

```bash
# Kill any running camera applications
pkill libcamera-hello
pkill rpicam-hello
pkill libcamera-vid
pkill rpicam-vid

# Or stop all libcamera processes
sudo pkill -f libcamera
```

### Step 2: Install Required Packages

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install picamera2 and dependencies for Pi Camera Module 3
sudo apt install -y python3-picamera2 python3-libcamera python3-kms++

# Install other Python dependencies
pip3 install websockets asyncio lgpio aiohttp pillow
```

### Step 3: Verify Camera is Detected

```bash
# Check if camera is detected
libcamera-hello --list-cameras

# You should see output like:
# Available cameras
# -----------------
# 0 : imx708 [4608x2592] (/base/soc/i2c0mux/i2c@1/imx708@1a)
#     Modes: 'SRGGB10_CSI2P' : 1536x864 [120.13 fps - (0, 0)/4608x2592 crop]
#                               2304x1296 [56.03 fps - (0, 0)/4608x2592 crop]
#                               4608x2592 [14.35 fps - (0, 0)/4608x2592 crop]
```

If you see "No cameras available", check:
1. Camera cable is properly connected to the Pi 5
2. Camera is connected to the correct port (Camera 0 port next to HDMI)
3. Cable is inserted with contacts facing the right way

### Step 4: Test Camera with Simple Command

```bash
# Take a test photo
libcamera-jpeg -o test.jpg

# If this works, your camera is properly set up!
```

### Step 5: Start the Python Server

```bash
# Navigate to your project directory
cd ~/your-project-directory

# Run the server
python3 raspberry-pi-server.py
```

You should see:
```
✅ Camera initialized successfully (1280x720 @ 10Mbps MJPEG)
✅ Pi Camera Module 3 ready for streaming
📹 HTTP Camera Server started on port 8080
```

### Step 6: Test Camera Stream in Browser

1. Find your Pi's IP address:
   ```bash
   hostname -I
   # Example output: 192.168.1.100
   ```

2. Open a browser and visit: `http://192.168.1.100:8080/`
   - You should see the camera feed
   - This confirms the camera streaming is working

### Step 7: Configure the Mobile App

1. Open the RC Car Controller app
2. Tap the ⚙️ Settings icon
3. Enter your Raspberry Pi's IP address (e.g., `192.168.1.100`)
4. Tap "SAVE & CONNECT"
5. The camera feed should appear in the app!

---

## Troubleshooting

### Issue: "Camera not available" in app

**Check 1: Is the server running?**
```bash
ps aux | grep raspberry-pi-server.py
```

**Check 2: Is port 8080 accessible?**
```bash
sudo netstat -tlnp | grep 8080
```

**Check 3: Can you access camera in browser?**
- Visit `http://YOUR_PI_IP:8080/` in a browser
- If this works but app doesn't, the issue is with the app connection
- If this doesn't work, the issue is with the server/camera

### Issue: "Failed to initialize camera"

**Solution 1: Stop other camera applications**
```bash
# Kill all camera processes
sudo pkill -f libcamera
sudo pkill -f rpicam

# Then restart the Python server
python3 raspberry-pi-server.py
```

**Solution 2: Reboot the Pi**
```bash
sudo reboot
```
After reboot, start only the Python server (no other camera apps).

**Solution 3: Check camera connection**
```bash
# This should show your camera
libcamera-hello --list-cameras

# If no cameras found:
# 1. Power off Pi: sudo shutdown -h now
# 2. Check camera cable connection
# 3. Make sure cable contacts face the right way
# 4. Power on Pi
```

### Issue: Camera works with libcamera-hello but not with Python server

This means another process is using the camera. The camera can only be used by ONE application at a time.

```bash
# Find what's using the camera
sudo lsof | grep libcamera

# Kill all camera processes
sudo pkill -f libcamera
sudo pkill -f rpicam

# Start Python server
python3 raspberry-pi-server.py
```

### Issue: Low framerate or choppy video

**Solution: Adjust resolution in server**

Edit `raspberry-pi-server.py` line ~125:
```python
# Lower resolution for better performance
config = self.camera.create_video_configuration(
    main={"size": (640, 480), "format": "RGB888"},  # Try this instead of 1280x720
    lores={"size": (320, 240)},
    encode="lores"
)
```

### Issue: Camera feed shows in browser but not in mobile app

**Check 1: Same network**
- Make sure phone and Pi are on the same WiFi network

**Check 2: IP address correct**
- In app settings, use the Pi's IP (from `hostname -I`)
- Don't use `localhost` or `127.0.0.1`

**Check 3: Firewall**
```bash
# Allow port 8080 through firewall
sudo ufw allow 8080
```

---

## Using Camera While Running Other Apps (Advanced)

If you absolutely need to use other camera apps while running the server, you need to use **multiple camera support**. However, this is complex and not recommended.

**Recommended approach:** Use ONLY the Python server for camera streaming, don't run other camera apps simultaneously.

---

## Camera Specifications - Pi Camera Module 3

- **Resolution:** 11.9 megapixels (4608 x 2592)
- **Sensor:** Sony IMX708
- **Video modes:**
  - 1536x864 @ 120 fps
  - 2304x1296 @ 56 fps
  - 4608x2592 @ 14 fps
- **Focus:** Auto-focus (standard version) or fixed focus (wide version)
- **Field of view:** 75° diagonal (standard), 120° diagonal (wide)

**Server uses:** 1280x720 @ 30fps for optimal streaming performance

---

## Commands Reference

```bash
# Check camera
libcamera-hello --list-cameras

# Test photo
libcamera-jpeg -o test.jpg

# Kill camera apps
pkill libcamera-hello
pkill rpicam-hello
sudo pkill -f libcamera

# Check what's running
ps aux | grep libcamera
ps aux | grep raspberry-pi-server

# Check ports
sudo netstat -tlnp | grep 8080
sudo netstat -tlnp | grep 8765

# View server logs (if using systemd)
journalctl -u rccar.service -f

# Restart Pi
sudo reboot
```

---

## Summary

1. **Stop** all other camera applications (`pkill libcamera-hello`, etc.)
2. **Install** required packages (`sudo apt install -y python3-picamera2`)
3. **Verify** camera is detected (`libcamera-hello --list-cameras`)
4. **Start** Python server (`python3 raspberry-pi-server.py`)
5. **Test** in browser (`http://PI_IP:8080/`)
6. **Configure** mobile app with Pi IP address
7. **Enjoy** live camera streaming! 🎥

The key is: **Only run the Python server, no other camera apps!**
