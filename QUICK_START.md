# 🚗 RC Car Quick Start Guide

## ✅ What's Fixed

The app now:
- **Detects ngrok connections** and shows appropriate warnings
- **Better error messages** with troubleshooting steps
- **Automatic handling** of camera availability based on connection type

---

## 🎯 Setup Options

### Option 1: Local Network (Recommended - FULL FEATURES)

✅ **Everything works**: Controls + Camera streaming

**On Raspberry Pi:**
```bash
# Start the server
python3 raspberry-pi-server.py

# Get your Pi's IP address
hostname -I
# Example output: 192.168.1.100
```

**In the mobile app:**
1. Tap ⚙️ Settings
2. Enter Pi's IP: `192.168.1.100`
3. Tap "SAVE & CONNECT"

✅ You'll see: WebSocket connected + Camera streaming

---

### Option 2: Remote Access via ngrok (Controls Only)

⚠️ **Controls work, but NO camera** (ngrok tunnels only 1 port)

**On Raspberry Pi:**

**Terminal 1** - Start Python server:
```bash
python3 raspberry-pi-server.py
```

**Terminal 2** - Start ngrok:
```bash
ngrok http 8765 --host-header=rewrite
```

Wait for ngrok to show:
```
Session Status: online
Forwarding: https://abc-123-xyz.ngrok-free.app -> http://localhost:8765
```

**In the mobile app:**
1. Tap ⚙️ Settings
2. Copy ONLY the hostname: `abc-123-xyz.ngrok-free.app`
   - ⚠️ No `https://`
   - ⚠️ No `ws://` or `wss://`
   - ⚠️ No port number
3. Tap "SAVE & CONNECT"

✅ You'll see: WebSocket connected + Warning that camera unavailable

---

## 🐛 Troubleshooting WebSocket Errors

### Error: "ngrok connection failed"

**Check 1: Is Python server running?**
```bash
ps aux | grep raspberry-pi-server.py
```
If not, start it:
```bash
python3 raspberry-pi-server.py
```

**Check 2: Is ngrok running and showing "online"?**
```bash
# Look for this line in ngrok output:
Session Status: online
```

If ngrok shows offline or errors:
```bash
# Restart ngrok
pkill -f ngrok
ngrok http 8765 --host-header=rewrite
```

**Check 3: Did you copy the hostname correctly?**
- ✅ Correct: `abc-123-xyz.ngrok-free.app`
- ❌ Wrong: `https://abc-123-xyz.ngrok-free.app`
- ❌ Wrong: `wss://abc-123-xyz.ngrok-free.app`
- ❌ Wrong: `abc-123-xyz.ngrok-free.app:8765`

**Check 4: Firewall/Network issues**
```bash
# Test if ngrok tunnel is accessible
curl https://YOUR-NGROK-URL.ngrok-free.app
```

---

## 📹 Camera Setup

### When using LOCAL network (same WiFi):

Camera automatically works at: `http://YOUR_PI_IP:8080/?action=stream`

**If camera doesn't show:**

1. **Stop other camera apps:**
```bash
pkill libcamera-hello
pkill rpicam-hello
sudo pkill -f libcamera
```

2. **Check camera is detected:**
```bash
libcamera-hello --list-cameras
```

3. **Restart Python server:**
```bash
# Stop it (Ctrl+C)
# Start it again
python3 raspberry-pi-server.py
```

4. **If still not working, reboot Pi:**
```bash
sudo reboot
```

Then start only the Python server.

### When using ngrok:

⚠️ **Camera streaming NOT available via ngrok** (by default)

**Why?** ngrok free tunnels only 1 port. We're using it for WebSocket (port 8765).

**Solutions:**
1. **Use same WiFi** for camera (controls via ngrok, camera via local network)
2. **Setup second ngrok tunnel** for port 8080 (requires ngrok paid plan)
3. **Use VPN** like Tailscale or WireGuard instead of ngrok

---

## 🎮 Testing the Setup

### Step 1: Check Connection Status
- App shows "CONNECTED" in green ✅

### Step 2: Test Controls
- Move throttle slider → Server logs show throttle commands
- Turn steering → Server logs show steering commands
- Press HONK → Server logs show honk on/off

### Step 3: Check Camera (if on same WiFi)
- Camera feed appears in draggable window
- "LIVE" indicator shows in top-right of camera
- Can drag and resize camera window

---

## 📝 Quick Command Reference

```bash
# Get Pi IP address
hostname -I

# Start server
python3 raspberry-pi-server.py

# Start ngrok (remote access)
ngrok http 8765 --host-header=rewrite

# Kill camera processes
pkill libcamera-hello && pkill rpicam-hello

# Check what's using camera
sudo lsof | grep libcamera

# Check ports
sudo netstat -tlnp | grep 8765  # WebSocket
sudo netstat -tlnp | grep 8080  # Camera

# Reboot Pi
sudo reboot
```

---

## ✨ What Changed in the App

1. **Automatic ngrok detection** - App knows when you're using ngrok
2. **Smart camera handling** - Camera only shows when available
3. **Better error messages** - Troubleshooting tips in the UI
4. **Connection status** - Clear indication of what's working
5. **Improved reconnection** - Auto-retry with backoff

---

## 🎯 Recommended Setup for Best Experience

**Development/Testing:**
- Use local network (same WiFi)
- Full features: controls + camera
- No external dependencies

**Remote Control:**
- Use VPN (Tailscale/WireGuard) instead of ngrok
- Everything works as if on local network
- More reliable than ngrok free tier
- No port limitations

**Quick Remote Demo:**
- Use ngrok for controls only
- Accept that camera won't work
- Great for showing off the control interface

---

Need help? Check the detailed guides:
- `SETUP_GUIDE.md` - Full server setup
- `CAMERA_SETUP.md` - Camera troubleshooting
