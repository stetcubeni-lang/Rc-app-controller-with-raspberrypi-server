# RC Car Controller - Setup Guide

## 📱 Mobile App

The mobile app is a React Native application built with Expo that provides a real-time controller interface for your RC car.

### Features
- **Throttle Control**: Vertical slider on the left (forward/backward)
- **Steering Control**: Horizontal slider on the bottom right (left/right)
- **3-Speed Gear System**: Radio buttons to select gear 1, 2, or 3
- **Lights Toggle**: Turn lights on/off
- **Connection Status**: Green indicator when connected, red when disconnected
- **Real-time PWM Display**: Shows current throttle and steering percentages

### Getting Started with the App
1. The app is already built and ready to use
2. Open it on your phone using the QR code or web preview
3. **Configure the server IP address:**
   - Tap the ⚙️ settings icon in the top right corner
   - Enter your Raspberry Pi's IP address (find it by running `hostname -I` on your Pi)
   - Tap "SAVE & CONNECT"
   - The IP address is saved automatically for next time
4. The app will automatically attempt to reconnect if the connection drops (up to 10 attempts)
5. Connection status is shown at the top:
   - 🟢 **CONNECTED** = Ready to control
   - 🔴 **DISCONNECTED** = Check server and IP settings

---

## 🍓 Raspberry Pi Server Setup

### 1. Prerequisites
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3 and pip (if not already installed)
sudo apt install python3 python3-pip -y

# Install required Python packages
pip3 install websockets asyncio
```

### 2. GPIO Setup
The server uses the following GPIO pins (BCM numbering):
- **GPIO 18**: Throttle motor PWM
- **GPIO 19**: Steering servo PWM
- **GPIO 17**: Lights control

### 3. Copy Server Code
Copy the `raspberry-pi-server.py` file to your Raspberry Pi:
```bash
# Option 1: Using scp from your computer
scp raspberry-pi-server.py pi@your-pi-ip:~/

# Option 2: Create file directly on Pi
nano ~/raspberry-pi-server.py
# Paste the code and save (Ctrl+X, Y, Enter)
```

### 4. Make It Executable
```bash
chmod +x raspberry-pi-server.py
```

### 5. Test the Server
```bash
python3 raspberry-pi-server.py
```

You should see:
```
🚗 RC Car WebSocket Server Starting...
Local IP: 192.168.1.X
Port: 8765
WebSocket URL: ws://192.168.1.X:8765
Waiting for connections...
```

### 6. Run on Startup (Optional)
To start the server automatically on boot:

```bash
# Create systemd service
sudo nano /etc/systemd/system/rccar.service
```

Add this content:
```ini
[Unit]
Description=RC Car WebSocket Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/raspberry-pi-server.py
WorkingDirectory=/home/pi
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl enable rccar.service
sudo systemctl start rccar.service

# Check status
sudo systemctl status rccar.service

# View logs
journalctl -u rccar.service -f
```

---

## 🌐 Remote Access Setup (Connect from Other Networks)

To control your RC car from anywhere (not just local WiFi network), you need to set up remote access:

### Option 1: Tailscale (Recommended - Easy & Secure) ⭐
**Best for**: Personal use, maximum security, works anywhere

1. Install Tailscale on Raspberry Pi:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. Install Tailscale on your phone from App Store/Play Store

3. Get your Pi's Tailscale IP:
   ```bash
   tailscale ip
   # You'll see an IP like 100.x.x.x
   ```

4. In the app settings, enter the Tailscale IP (e.g., `100.123.45.67`)

**Advantages:**
- ✅ Works from anywhere with internet
- ✅ Encrypted & secure
- ✅ No router configuration needed
- ✅ Free for personal use
- ✅ IP stays the same

### Option 2: ngrok (Quick Testing)
**Best for**: Quick demos, temporary access

1. Install ngrok on Raspberry Pi:
   ```bash
   wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
   sudo tar xvzf ngrok-v3-stable-linux-arm.tgz -C /usr/local/bin
   ```

2. Sign up at [ngrok.com](https://ngrok.com) and get your auth token:
   - Go to https://dashboard.ngrok.com/get-started/your-authtoken
   - Copy the authtoken from your dashboard
   - ⚠️ Important: Use YOUR actual authtoken, not the text "YOUR_TOKEN"

3. Authenticate:
   ```bash
   ngrok config add-authtoken YOUR_ACTUAL_AUTH_TOKEN_HERE
   ```
   Replace YOUR_ACTUAL_AUTH_TOKEN_HERE with the token from step 2

4. Start the ngrok tunnel:
   ```bash
   ngrok tcp 8765
   ```

5. You'll see output like:
   ```
   Forwarding    tcp://0.tcp.ngrok.io:12345 -> localhost:8765
   ```

6. In the app settings, enter ONLY THE HOST AND PORT: `0.tcp.ngrok.io:12345`
   - ⚠️ Don't include `tcp://` or `ws://` - the app adds it automatically

**Advantages:**
- ✅ Very quick to set up
- ✅ Works from anywhere
- ✅ No router configuration

**Disadvantages:**
- ❌ URL changes every time you restart ngrok (unless you pay)
- ❌ Free tier has connection limits
- ❌ Adds some latency

### Option 3: Port Forwarding (Advanced)
**Best for**: Permanent setup, maximum control

1. Find your Raspberry Pi's local IP:
   ```bash
   hostname -I
   # Note the first IP (e.g., 192.168.1.100)
   ```

2. Set a static IP for your Pi (recommended):
   ```bash
   # Edit dhcpcd.conf
   sudo nano /etc/dhcpcd.conf
   
   # Add at the end:
   interface wlan0
   static ip_address=192.168.1.100/24
   static routers=192.168.1.1
   static domain_name_servers=8.8.8.8 8.8.4.4
   
   # Save and reboot
   sudo reboot
   ```

3. Configure port forwarding on your router:
   - Login to your router (usually 192.168.1.1 or 192.168.0.1)
   - Find "Port Forwarding" settings
   - Add a new rule:
     - **External Port**: 8765
     - **Internal IP**: Your Pi's IP (e.g., 192.168.1.100)
     - **Internal Port**: 8765
     - **Protocol**: TCP

4. Find your public IP:
   ```bash
   curl ifconfig.me
   ```

5. In the app settings, enter your public IP: `YOUR_PUBLIC_IP`
   - Don't include port, the app uses 8765 by default

**Advantages:**
- ✅ No third-party services
- ✅ Full control
- ✅ Low latency

**Disadvantages:**
- ❌ Exposes your network to the internet
- ❌ Public IP might change (use DDNS to fix this)
- ❌ Router configuration required
- ⚠️ **Security Warning**: Your server is accessible to anyone on the internet! Add authentication if you use this method.

---

## 🔧 Hardware Connections

### Motor Controller (Example: L298N)
- **Throttle PWM (GPIO 18)** → Motor driver PWM input
- **GND** → Common ground
- **5V** → Motor driver logic power

### Steering Servo
- **Steering PWM (GPIO 19)** → Servo signal wire (usually orange/yellow)
- **5V** → Servo power (red wire)
- **GND** → Servo ground (brown/black wire)

### Lights
- **Lights Control (GPIO 17)** → LED through 220Ω resistor
- **GND** → LED cathode

---

## 📊 Testing

### 1. Test Without Hardware
The server runs in simulation mode if GPIO library is not available. Perfect for testing the connection:
```bash
python3 raspberry-pi-server.py
```

### 2. Test With Hardware
Once connected, you should see logs like:
```
🚗 THROTTLE: 75.0% (Gear: 2)
🎯 STEERING: -30.0%
⚙️  GEAR: 2
💡 LIGHTS: ON
```

### 3. Monitor Connection
Watch the connection status indicator in the app:
- 🟢 Green = Connected
- 🔴 Red = Disconnected

---

## 🐛 Troubleshooting

### App can't connect to server
**Error: "Connection failed. Is the server running?"**

1. **Verify Raspberry Pi IP address:**
   ```bash
   hostname -I
   ```
   Use the first IP address shown (usually starts with 192.168.x.x)

2. **Check if server is running:**
   ```bash
   sudo systemctl status rccar.service
   # OR if running manually:
   ps aux | grep raspberry-pi-server
   ```

3. **Test server is accessible:**
   ```bash
   # On Pi, check if port 8765 is listening
   sudo netstat -tlnp | grep 8765
   ```

4. **Check firewall (if enabled):**
   ```bash
   sudo ufw allow 8765
   sudo ufw status
   ```

5. **Verify network connection:**
   - Ensure both devices are on the same WiFi network
   - Try pinging the Pi from your phone/computer:
     ```bash
     ping 192.168.1.X
     ```
   - Or use a VPN like Tailscale if on different networks

6. **Check the app settings:**
   - Tap the ⚙️ settings icon in the app
   - Verify the IP address matches your Pi's IP
   - Make sure there are no typos or extra spaces
   - For local network: Use local IP (e.g., `192.168.1.100`)
   - For Tailscale: Use Tailscale IP (e.g., `100.123.45.67`)
   - For ngrok: Use ngrok address without protocol (e.g., `0.tcp.ngrok.io:12345`)
   - For port forwarding: Use public IP (find with `curl ifconfig.me` on Pi)

7. **Server console logs:**
   Look for connection messages in the server output:
   ```bash
   # If using systemd:
   journalctl -u rccar.service -f
   
   # If running manually:
   # Check the terminal where server is running
   ```

### GPIO errors
1. Install GPIO library: `pip3 install RPi.GPIO`
2. Run with sudo if permission error: `sudo python3 raspberry-pi-server.py`

### Server crashes
1. Check logs: `journalctl -u rccar.service -n 50`
2. Test manually: `python3 raspberry-pi-server.py`

---

## 🎮 Usage Tips

1. **Start with Gear 1** for testing
2. **Release throttle/steering** - sliders auto-return to center
3. **Connection auto-reconnects** every 3 seconds if disconnected
4. **PWM values** are logged to server console for debugging

---

## 📝 Customization

### Change GPIO Pins
Edit `raspberry-pi-server.py`:
```python
THROTTLE_PIN = 18  # Change to your pin
STEERING_PIN = 19  # Change to your pin
LIGHTS_PIN = 17    # Change to your pin
```

### Adjust PWM Values
Modify the duty cycle calculations in `set_throttle()` and `set_steering()` methods based on your hardware.

### Change Server Port
If you want to use a different port (default is 8765):

1. In `raspberry-pi-server.py`, change line 216:
   ```python
   async with websockets.serve(handle_client, "0.0.0.0", YOUR_PORT):
   ```

2. In the app, tap settings and enter: `YOUR_IP:YOUR_PORT`

---

## 🚀 Next Steps

1. Set up remote access with Tailscale/ngrok
2. Test all controls with your RC car
3. Fine-tune PWM values for smooth operation
4. Add more features (speed presets, emergency stop, etc.)

Enjoy your RC car! 🏎️
