#!/usr/bin/env python3
"""
RC Car WebSocket Server + Camera Streaming for Raspberry Pi
============================================================

This server receives commands from the mobile app, controls the RC car,
and streams the Raspberry Pi Camera Module 3 feed over HTTP using libcamera-vid.
It automatically starts ngrok tunnel for remote access.

Requirements:
    pip install websockets asyncio lgpio aiohttp
    libcamera-apps should be pre-installed on Raspberry Pi OS
    Install ngrok: https://ngrok.com/download

Hardware Setup - GPIO Pin Assignments:
    ========================================
    PIN ASSIGNMENT LIST:
    ========================================
    GPIO 18  - Throttle Forward PWM (0-100%, forward direction)
    GPIO 19  - Throttle Backward PWM (0-100%, backward direction)
    GPIO 20  - Steering Right PWM (0-100%, right direction)
    GPIO 21  - Steering Left PWM (0-100%, left direction)
    GPIO 17  - Lights (Digital on/off)
    GPIO 27  - Auto Mode (Digital on/off)
    GPIO 22  - Brake PWM (0-100%)
    GPIO 23  - Honk (Digital, active when pressed)
    GPIO 24  - Gear 1 (Digital, active when selected)
    GPIO 25  - Gear 2 (Digital, active when selected)
    GPIO 26  - Gear 3 (Digital, active when selected)
    ========================================

Network Setup (for remote access):
    1. Install ngrok or use a VPN service like WireGuard, Tailscale, or ZeroTier
    2. For ngrok: ngrok tcp 8765
    3. Update the WebSocket URL in the mobile app with your Pi's IP or ngrok URL

Usage:
    python3 raspberry-pi-server.py
"""

import asyncio
import json
import websockets
import logging
import subprocess
import time
import shutil
import threading
from typing import Set
from aiohttp import web

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import lgpio for actual hardware control (Raspberry Pi 5 compatible)
try:
    import lgpio
    GPIO_AVAILABLE = True
    logger.info("lgpio library loaded - hardware control enabled")
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("lgpio library not available - running in simulation mode")

# Check if libcamera-vid or rpicam-vid is available for camera streaming
CAMERA_AVAILABLE = shutil.which('libcamera-vid') is not None or shutil.which('rpicam-vid') is not None
if CAMERA_AVAILABLE:
    logger.info("libcamera-vid/rpicam-vid found - camera streaming enabled")
else:
    logger.warning("libcamera-vid not available - camera streaming disabled")
    logger.warning("Install with: sudo apt install -y libcamera-apps")

# ========================================
# GPIO PIN ASSIGNMENT LIST
# ========================================
THROTTLE_FORWARD_PIN = 18   # PWM: Throttle forward (0-100%)
THROTTLE_BACKWARD_PIN = 19  # PWM: Throttle backward (0-100%)
STEERING_RIGHT_PIN = 20     # PWM: Steering right (0-100%)
STEERING_LEFT_PIN = 21      # PWM: Steering left (0-100%)
LIGHTS_PIN = 17             # Digital: Lights on/off
AUTO_PIN = 27               # Digital: Auto mode on/off
BRAKE_PIN = 22              # PWM: Brake control (0-100%)
HONK_PIN = 23               # Digital: Honk (active when pressed)
GEAR_1_PIN = 24             # Digital: Gear 1 active
GEAR_2_PIN = 25             # Digital: Gear 2 active
GEAR_3_PIN = 26             # Digital: Gear 3 active
# ========================================

# PWM frequency (Hz)
PWM_FREQUENCY = 50

# Connected clients
connected_clients: Set[websockets.WebSocketServerProtocol] = set()

# Camera streaming using libcamera-vid
class CameraStreamer:
    """Manages Raspberry Pi Camera Module 3 streaming using libcamera-vid"""
    def __init__(self):
        self.camera_process = None
        self.frame_buffer = None
        self.frame_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.reader_thread = None
        
        if CAMERA_AVAILABLE:
            self.setup_camera()
    
    def setup_camera(self):
        """Initialize camera using libcamera-vid or rpicam-vid command"""
        try:
            logger.info("Starting Raspberry Pi Camera Module 3...")
            
            # Determine which command to use
            camera_cmd = 'rpicam-vid' if shutil.which('rpicam-vid') else 'libcamera-vid'
            
            # Start libcamera-vid process
            # Output MJPEG stream to stdout, 640x480 for performance
            cmd = [
                camera_cmd,
                '-t', '0',  # Run indefinitely
                '--width', '640',
                '--height', '480',
                '--framerate', '30',
                '--codec', 'mjpeg',
                '--inline',  # Inline headers
                '-o', '-',  # Output to stdout
                '--nopreview',  # No preview window
            ]
            
            self.camera_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )
            
            # Start reader thread
            self.reader_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.reader_thread.start()
            
            time.sleep(2)  # Give camera time to warm up
            logger.info(f"✅ Camera initialized successfully using {camera_cmd}")
            logger.info("✅ Pi Camera Module 3 ready for streaming (640x480 @ 30fps MJPEG)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize camera: {e}")
            logger.error("   Troubleshooting steps:")
            logger.error("   1. Stop other camera apps: pkill libcamera-vid && pkill rpicam-vid")
            logger.error("   2. Check camera is detected: libcamera-hello --list-cameras")
            logger.error("   3. Install packages: sudo apt install -y libcamera-apps")
            logger.error("   4. Reboot Pi if needed: sudo reboot")
            self.camera_process = None
    
    def _read_frames(self):
        """Read frames from libcamera-vid stdout in background thread"""
        if not self.camera_process:
            return
        
        buffer = b''
        while not self.stop_flag.is_set():
            try:
                chunk = self.camera_process.stdout.read(4096)
                if not chunk:
                    break
                
                buffer += chunk
                
                # Find JPEG markers
                start = buffer.find(b'\xff\xd8')  # JPEG start
                end = buffer.find(b'\xff\xd9')    # JPEG end
                
                if start != -1 and end != -1 and end > start:
                    # Extract complete JPEG frame
                    frame = buffer[start:end+2]
                    with self.frame_lock:
                        self.frame_buffer = frame
                    
                    # Remove processed frame from buffer
                    buffer = buffer[end+2:]
            except Exception as e:
                logger.error(f"Frame read error: {e}")
                break
    
    def get_frame(self):
        """Get latest frame"""
        with self.frame_lock:
            return self.frame_buffer
    
    def cleanup(self):
        """Stop camera"""
        logger.info("Stopping camera...")
        self.stop_flag.set()
        
        if self.camera_process:
            try:
                self.camera_process.terminate()
                self.camera_process.wait(timeout=5)
                logger.info("Camera stopped")
            except:
                try:
                    self.camera_process.kill()
                except:
                    pass
        
        if self.reader_thread:
            self.reader_thread.join(timeout=2)

# Initialize camera
camera_streamer = None
if CAMERA_AVAILABLE:
    camera_streamer = CameraStreamer()

class RCCarController:
    """Controls the RC car hardware via GPIO"""
    
    def __init__(self):
        self.gpio_chip = None
        self.current_gear = 1
        self.lights_on = False
        self.auto_mode = False
        self.honk_active = False
        self.throttle_forward_duty = 0
        self.throttle_backward_duty = 0
        self.steering_right_duty = 0
        self.steering_left_duty = 0
        self.brake_duty = 0
        
        if GPIO_AVAILABLE:
            self.setup_gpio()
    
    def setup_gpio(self):
        """Initialize GPIO pins and PWM"""
        try:
            # Open GPIO chip (gpiochip4 on Raspberry Pi 5)
            self.gpio_chip = lgpio.gpiochip_open(4)
            
            # Claim GPIO pins for output
            lgpio.gpio_claim_output(self.gpio_chip, THROTTLE_FORWARD_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, THROTTLE_BACKWARD_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, STEERING_RIGHT_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, STEERING_LEFT_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, LIGHTS_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, AUTO_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, BRAKE_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, HONK_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, GEAR_1_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, GEAR_2_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, GEAR_3_PIN)
            
            # Setup PWM for throttle forward/backward (50Hz frequency)
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_FORWARD_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_BACKWARD_PIN, PWM_FREQUENCY, 0)
            
            # Setup PWM for steering right/left (50Hz frequency)
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, 0)
            
            # Setup PWM for brake (50Hz frequency)
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 0)
            
            # Lights off initially
            lgpio.gpio_write(self.gpio_chip, LIGHTS_PIN, 0)
            
            # Auto mode off initially
            lgpio.gpio_write(self.gpio_chip, AUTO_PIN, 0)
            
            # Honk off initially
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 0)
            
            # Gear 1 on by default
            lgpio.gpio_write(self.gpio_chip, GEAR_1_PIN, 1)
            lgpio.gpio_write(self.gpio_chip, GEAR_2_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, GEAR_3_PIN, 0)
            
            logger.info("GPIO initialized successfully on gpiochip4 (Pi 5)")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            self.gpio_chip = None
    
    def set_throttle_forward(self, percentage: float):
        """
        Set throttle forward PWM
        percentage: 0 to 100 (forward direction)
        """
        logger.info(f"🚗 THROTTLE FORWARD: {percentage:.1f}% (Gear: {self.current_gear})")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            # Convert percentage to PWM duty cycle (0-100)
            duty_cycle = percentage * (self.current_gear / 3)
            self.throttle_forward_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_FORWARD_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_throttle_backward(self, percentage: float):
        """
        Set throttle backward PWM
        percentage: 0 to 100 (backward direction)
        """
        logger.info(f"🚗 THROTTLE BACKWARD: {percentage:.1f}% (Gear: {self.current_gear})")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            # Convert percentage to PWM duty cycle (0-100)
            duty_cycle = percentage * (self.current_gear / 3)
            self.throttle_backward_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_BACKWARD_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_steering_right(self, percentage: float):
        """
        Set steering right PWM
        percentage: 0 to 100 (right direction)
        """
        logger.info(f"🎯 STEERING RIGHT: {percentage:.1f}%")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            duty_cycle = percentage
            self.steering_right_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_steering_left(self, percentage: float):
        """
        Set steering left PWM
        percentage: 0 to 100 (left direction)
        """
        logger.info(f"🎯 STEERING LEFT: {percentage:.1f}%")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            duty_cycle = percentage
            self.steering_left_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_gear(self, gear: int):
        """Set gear (1, 2, or 3)"""
        if 1 <= gear <= 3:
            self.current_gear = gear
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.gpio_write(self.gpio_chip, GEAR_1_PIN, 1 if gear == 1 else 0)
                lgpio.gpio_write(self.gpio_chip, GEAR_2_PIN, 1 if gear == 2 else 0)
                lgpio.gpio_write(self.gpio_chip, GEAR_3_PIN, 1 if gear == 3 else 0)
            logger.info(f"⚙️  GEAR: {gear}")
    
    def set_lights(self, on: bool):
        """Toggle lights"""
        self.lights_on = on
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, LIGHTS_PIN, 1 if on else 0)
        logger.info(f"💡 LIGHTS: {'ON' if on else 'OFF'}")
    
    def set_auto_mode(self, on: bool):
        """Toggle auto mode"""
        self.auto_mode = on
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, AUTO_PIN, 1 if on else 0)
        logger.info(f"🤖 AUTO MODE: {'ON' if on else 'OFF'}")
    
    def set_brake(self, percentage: float):
        """
        Set brake PWM
        percentage: 0 (no brake) to 100 (full brake)
        """
        logger.info(f"🛑 BRAKE: {percentage:.1f}%")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            # Convert percentage to PWM duty cycle
            duty_cycle = (percentage / 100) * 100
            self.brake_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_honk(self, active: bool):
        """Toggle honk"""
        self.honk_active = active
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 1 if active else 0)
        logger.info(f"📢 HONK: {'ON' if active else 'OFF'}")
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            # Stop PWM signals
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_FORWARD_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_BACKWARD_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 0)
            
            # Turn off digital outputs
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 0)
            
            # Free GPIO pins
            lgpio.gpio_free(self.gpio_chip, THROTTLE_FORWARD_PIN)
            lgpio.gpio_free(self.gpio_chip, THROTTLE_BACKWARD_PIN)
            lgpio.gpio_free(self.gpio_chip, STEERING_RIGHT_PIN)
            lgpio.gpio_free(self.gpio_chip, STEERING_LEFT_PIN)
            lgpio.gpio_free(self.gpio_chip, LIGHTS_PIN)
            lgpio.gpio_free(self.gpio_chip, AUTO_PIN)
            lgpio.gpio_free(self.gpio_chip, BRAKE_PIN)
            lgpio.gpio_free(self.gpio_chip, HONK_PIN)
            lgpio.gpio_free(self.gpio_chip, GEAR_1_PIN)
            lgpio.gpio_free(self.gpio_chip, GEAR_2_PIN)
            lgpio.gpio_free(self.gpio_chip, GEAR_3_PIN)
            
            # Close GPIO chip
            lgpio.gpiochip_close(self.gpio_chip)
            logger.info("GPIO cleanup completed")

# Initialize RC car controller
rc_car = RCCarController()

async def handle_client(websocket: websockets.WebSocketServerProtocol):
    """Handle WebSocket client connection"""
    client_address = websocket.remote_address
    logger.info(f"✅ Client connected: {client_address}")
    connected_clients.add(websocket)
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                command_type = data.get('type')
                
                if command_type == 'throttle_forward':
                    value = data.get('value', 0)
                    rc_car.set_throttle_forward(value)
                
                elif command_type == 'throttle_backward':
                    value = data.get('value', 0)
                    rc_car.set_throttle_backward(value)
                
                elif command_type == 'steering_right':
                    value = data.get('value', 0)
                    rc_car.set_steering_right(value)
                
                elif command_type == 'steering_left':
                    value = data.get('value', 0)
                    rc_car.set_steering_left(value)
                
                elif command_type == 'brake':
                    value = data.get('value', 0)
                    rc_car.set_brake(value)
                
                elif command_type == 'honk':
                    value = data.get('value', False)
                    rc_car.set_honk(value)
                
                elif command_type == 'settings':
                    gear = data.get('gear', 1)
                    lights = data.get('lights', False)
                    auto = data.get('auto', False)
                    rc_car.set_gear(gear)
                    rc_car.set_lights(lights)
                    rc_car.set_auto_mode(auto)
                
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {message}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"❌ Client disconnected: {client_address}")
    finally:
        connected_clients.remove(websocket)
        # Reset to safe state when client disconnects
        rc_car.set_throttle_forward(0)
        rc_car.set_throttle_backward(0)
        rc_car.set_steering_right(0)
        rc_car.set_steering_left(0)
        rc_car.set_brake(0)
        rc_car.set_honk(False)

# HTTP handlers for camera streaming
async def stream_handler(request):
    """MJPEG stream handler for continuous streaming"""
    if not camera_streamer or not camera_streamer.camera_process:
        logger.warning("Camera stream requested but camera not available")
        return web.Response(text="Camera not available. Make sure camera is connected and not used by other apps.", status=503)
    
    logger.info(f"Camera stream started for client {request.remote}")
    
    response = web.StreamResponse()
    response.content_type = 'multipart/x-mixed-replace; boundary=FRAME'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'close'
    await response.prepare(request)
    
    frame_count = 0
    last_frame = None
    try:
        while True:
            frame = camera_streamer.get_frame()
            
            # Only send if we have a new frame
            if frame and frame != last_frame:
                frame_count += 1
                last_frame = frame
                
                if frame_count % 30 == 0:
                    logger.info(f"Streamed {frame_count} frames to {request.remote}")
                
                await response.write(
                    b'--FRAME\r\n'
                    b'Content-Type: image/jpeg\r\n'
                    b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + 
                    frame + b'\r\n'
                )
            
            await asyncio.sleep(0.033)  # ~30 FPS
    except (asyncio.CancelledError, ConnectionResetError):
        logger.info(f"Camera stream closed for client {request.remote} (streamed {frame_count} frames)")
    except Exception as e:
        logger.error(f"Stream error for {request.remote}: {e}")
    finally:
        await response.write_eof()
    
    return response

async def root_handler(request):
    """Root handler - info page"""
    action = request.query.get('action', '')
    
    if action == 'stream':
        return await stream_handler(request)
    
    camera_status = "✅ Active (Pi Camera Module 3)" if (camera_streamer and camera_streamer.camera_process) else "❌ Not Available"
    
    html = """
    <html>
    <head>
        <title>RC Car Camera - Pi Camera Module 3</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { 
                background: #1a1410; 
                color: #f59e0b; 
                font-family: monospace; 
                padding: 20px;
                text-align: center;
                margin: 0;
            }
            img { 
                max-width: 100%; 
                height: auto;
                border: 2px solid #f59e0b; 
                border-radius: 8px;
                display: block;
                margin: 20px auto;
            }
            h1 { color: #f59e0b; margin-bottom: 10px; }
            .status { 
                padding: 10px; 
                background: rgba(245, 158, 11, 0.2); 
                border-radius: 8px;
                display: inline-block;
                margin: 10px 0;
            }
            .info { 
                background: rgba(0,0,0,0.3); 
                padding: 15px; 
                border-radius: 8px;
                margin: 20px auto;
                max-width: 600px;
                text-align: left;
            }
        </style>
    </head>
    <body>
        <h1>🎥 RC Car Camera Stream</h1>
        <div class="status">Camera Status: """ + camera_status + """</div>
        """ + ("""
        <img src="/?action=stream" alt="Pi Camera Module 3 Stream" />
        <div class="info">
            <p><strong>Stream URL for Mobile App:</strong></p>
            <p><code>http://YOUR_PI_IP:8080/?action=stream</code></p>
            <p><strong>Resolution:</strong> 640x480 @ 30fps</p>
            <p><strong>Encoder:</strong> MJPEG (libcamera-vid)</p>
        </div>
        """ if (camera_streamer and camera_streamer.camera_process) else """
        <div class="info">
            <p><strong>❌ Camera Not Available</strong></p>
            <p><strong>Troubleshooting:</strong></p>
            <ol style="text-align: left;">
                <li>Check camera connection: <code>libcamera-hello --list-cameras</code></li>
                <li>Stop other camera apps: <code>pkill libcamera-vid && pkill rpicam-vid</code></li>
                <li>Install libcamera-apps: <code>sudo apt install -y libcamera-apps</code></li>
                <li>Reboot if needed: <code>sudo reboot</code></li>
            </ol>
        </div>
        """) + """
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def start_http_server():
    """Start HTTP server for camera streaming"""
    app = web.Application()
    app.router.add_get('/', root_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("📹 HTTP Camera Server started on port 8080")

async def start_ngrok():
    """Start ngrok tunnel in background"""
    try:
        # Check if ngrok is installed
        result = subprocess.run(['which', 'ngrok'], capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("⚠️  ngrok not installed. Install from: https://ngrok.com/download")
            return None
        
        # Kill any existing ngrok processes
        subprocess.run(['pkill', '-f', 'ngrok'], stderr=subprocess.DEVNULL)
        time.sleep(1)
        
        # Start ngrok in background
        ngrok_process = subprocess.Popen(
            ['ngrok', 'http', '8765', '--host-header=rewrite'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        logger.info("🌐 Starting ngrok tunnel...")
        time.sleep(3)  # Wait for ngrok to start
        
        # Get ngrok URL from API
        try:
            import urllib.request
            with urllib.request.urlopen('http://localhost:4040/api/tunnels') as response:
                data = json.loads(response.read())
                if data.get('tunnels'):
                    public_url = data['tunnels'][0]['public_url']
                    # Extract hostname from URL
                    hostname = public_url.replace('https://', '').replace('http://', '')
                    logger.info(f"✅ ngrok tunnel active: {hostname}")
                    return hostname
        except Exception as e:
            logger.warning(f"⚠️  Could not get ngrok URL: {e}")
        
        return None
    except Exception as e:
        logger.error(f"❌ Failed to start ngrok: {e}")
        return None

async def main():
    """Start WebSocket server and HTTP camera server"""
    # Get local IP address
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "unknown"
    
    # Start HTTP server for camera
    await start_http_server()
    
    # Start ngrok tunnel
    ngrok_url = await start_ngrok()
    
    print("\n" + "=" * 70)
    print("🚗 RC Car WebSocket Server + Camera Streaming")
    print("=" * 70)
    print(f"Local Network IP: {local_ip}")
    print(f"WebSocket Port: 8765")
    print(f"Camera HTTP Port: 8080")
    print("=" * 70)
    print("\n📌 GPIO PIN ASSIGNMENTS:")
    print("=" * 70)
    print(f"  GPIO {THROTTLE_FORWARD_PIN:2d} - Throttle Forward PWM (0-100%, forward direction)")
    print(f"  GPIO {THROTTLE_BACKWARD_PIN:2d} - Throttle Backward PWM (0-100%, backward direction)")
    print(f"  GPIO {STEERING_RIGHT_PIN:2d} - Steering Right PWM (0-100%, right direction)")
    print(f"  GPIO {STEERING_LEFT_PIN:2d} - Steering Left PWM (0-100%, left direction)")
    print(f"  GPIO {LIGHTS_PIN:2d} - Lights (Digital on/off)")
    print(f"  GPIO {AUTO_PIN:2d} - Auto Mode (Digital on/off)")
    print(f"  GPIO {BRAKE_PIN:2d} - Brake PWM (0-100%)")
    print(f"  GPIO {HONK_PIN:2d} - Honk (Digital, active when pressed)")
    print(f"  GPIO {GEAR_1_PIN:2d} - Gear 1 (Digital, active when selected)")
    print(f"  GPIO {GEAR_2_PIN:2d} - Gear 2 (Digital, active when selected)")
    print(f"  GPIO {GEAR_3_PIN:2d} - Gear 3 (Digital, active when selected)")
    print("=" * 70)
    print("")
    print("📱 PASTE THIS IN YOUR APP SETTINGS:")
    print("")
    print("   LOCAL NETWORK (same WiFi):")
    print(f"   ┌────────────────────────────────────────┐")
    print(f"   │  {local_ip:<38}│")
    print(f"   └────────────────────────────────────────┘")
    print("")
    print("   REMOTE ACCESS (ngrok):")
    if ngrok_url:
        print("   ✅ ngrok tunnel is ACTIVE!")
        print("   Paste into app settings:")
        print("   ┌────────────────────────────────────────┐")
        print(f"   │  {ngrok_url:<38}│")
        print("   └────────────────────────────────────────┘")
        print("")
        print("   ⚠️  Copy ONLY hostname - no https://, no wss://, no port!")
        print("   ⚠️  WebSocket upgrade happens automatically")
    else:
        print("   ❌ ngrok not started automatically")
        print("   Manual setup:")
        print("   1. Open NEW terminal window")
        print("   2. Run: ngrok http 8765 --host-header=rewrite")
        print("   3. Look for: Forwarding https://xxxx.ngrok-free.app -> http://localhost:8765")
        print("   4. Copy ONLY the hostname (e.g., joline-unfauceted-zayne.ngrok-free.app)")
        print("   5. Paste into app settings")
        print("")
        print("   ⚠️  Copy ONLY hostname - no https://, no wss://, no port!")
    print("")
    print("📹 CAMERA STREAM:")
    print("=" * 70)
    if CAMERA_AVAILABLE and camera_streamer and camera_streamer.camera_process:
        print(f"   ✅ Camera Active (libcamera-vid)")
        print(f"   Local: http://{local_ip}:8080/?action=stream")
        print(f"   View in browser: http://{local_ip}:8080/")
    else:
        print("   ❌ Camera Not Available")
        print("   Install: sudo apt install -y libcamera-apps")
        print("   Stop other apps: pkill libcamera-vid && pkill rpicam-vid")
        print("   Check detection: libcamera-hello --list-cameras")
    print("=" * 70)
    print("")
    
    if not GPIO_AVAILABLE:
        logger.warning("⚠️  Running in SIMULATION MODE (no GPIO)")
        logger.warning("⚠️  Install lgpio for actual hardware control: pip install lgpio")
    
    logger.info("\n✅ Server is running. Waiting for connections...\n")
    
    # Configure WebSocket server to accept all origins (needed for ngrok)
    async with websockets.serve(
        handle_client, 
        "0.0.0.0", 
        8765,
        # Allow connections from any origin (ngrok, local network, etc.)
        origins=None,
        # Increase ping interval and timeout for ngrok stability
        ping_interval=20,
        ping_timeout=20
    ):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Server stopped by user")
    finally:
        rc_car.cleanup()
        if camera_streamer:
            camera_streamer.cleanup()
