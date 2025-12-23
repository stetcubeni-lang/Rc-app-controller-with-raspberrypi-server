#!/usr/bin/env python3
"""
RC Car WebSocket Server + Camera Streaming for Raspberry Pi
============================================================

This server receives commands from the mobile app, controls the RC car,
and streams the Raspberry Pi Camera Module 3 feed over HTTP.
It automatically starts ngrok tunnel for remote access.

Requirements:
    pip install websockets asyncio lgpio aiohttp
    sudo apt install -y python3-picamera2 python3-libcamera python3-kms++
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
from typing import Set
from aiohttp import web
import io

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

# Try to import picamera2 for camera streaming
try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    import threading
    CAMERA_AVAILABLE = True
    logger.info("picamera2 library loaded - camera streaming enabled")
except ImportError:
    CAMERA_AVAILABLE = False
    logger.warning("picamera2 library not available - camera streaming disabled")
    logger.warning("Install with: sudo apt install -y python3-picamera2 python3-libcamera python3-kms++")

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

# Camera streaming
class StreamingOutput(io.BufferedIOBase):
    """Buffer for camera frames"""
    def __init__(self):
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = threading.Condition()

    def write(self, buf):
        if buf.startswith(b'\xff\xd8'):
            # Start of new JPEG frame
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
            self.buffer.truncate()
        self.buffer.write(buf)

class CameraStreamer:
    """Manages Raspberry Pi Camera Module 3 streaming"""
    def __init__(self):
        self.camera = None
        self.output = None
        self.encoder = None
        
        if CAMERA_AVAILABLE:
            self.setup_camera()
    
    def setup_camera(self):
        """Initialize camera for Raspberry Pi Camera Module 3"""
        try:
            logger.info("Initializing Raspberry Pi Camera Module 3...")
            
            # Kill any existing camera processes
            try:
                subprocess.run(['pkill', '-f', 'libcamera'], stderr=subprocess.DEVNULL, timeout=2)
                subprocess.run(['pkill', '-f', 'rpicam'], stderr=subprocess.DEVNULL, timeout=2)
                time.sleep(1)
                logger.info("Stopped any existing camera processes")
            except:
                pass
            
            self.camera = Picamera2()
            
            # Configure camera for streaming with MJPEG
            # Raspberry Pi Camera Module 3 supports up to 4608x2592
            # Using 1280x720 for good quality and performance
            config = self.camera.create_video_configuration(
                main={"size": (1280, 720), "format": "RGB888"},
                lores={"size": (640, 480)},
                encode="lores"
            )
            self.camera.configure(config)
            
            # Create output buffer
            self.output = StreamingOutput()
            self.encoder = MJPEGEncoder(bitrate=10000000)  # 10Mbps for good quality
            
            # Start camera
            self.camera.start()
            time.sleep(2)  # Give camera time to warm up
            self.camera.start_recording(self.encoder, FileOutput(self.output))
            
            logger.info("✅ Camera initialized successfully (1280x720 @ 10Mbps MJPEG)")
            logger.info("✅ Pi Camera Module 3 ready for streaming")
        except Exception as e:
            logger.error(f"❌ Failed to initialize camera: {e}")
            logger.error("   Troubleshooting steps:")
            logger.error("   1. Stop other camera apps: pkill libcamera-hello && pkill rpicam-hello")
            logger.error("   2. Check camera is detected: libcamera-hello --list-cameras")
            logger.error("   3. Install packages: sudo apt install -y python3-picamera2 python3-libcamera")
            logger.error("   4. Reboot Pi if needed: sudo reboot")
            self.camera = None
    
    def get_frame(self):
        """Get latest frame"""
        if not self.output:
            return None
        
        with self.output.condition:
            self.output.condition.wait(timeout=1.0)
            frame = self.output.frame
            if frame:
                return frame
            return None
    
    def cleanup(self):
        """Stop camera"""
        if self.camera:
            try:
                self.camera.stop_recording()
                self.camera.close()
                logger.info("Camera stopped")
            except:
                pass

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
    if not camera_streamer or not camera_streamer.camera:
        logger.warning("Camera stream requested but camera not available")
        return web.Response(text="Camera not available. Make sure camera is connected and not used by other apps.", status=503)
    
    logger.info(f"Camera stream started for client {request.remote}")
    
    response = web.StreamResponse()
    response.content_type = 'multipart/x-mixed-replace; boundary=FRAME'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'close'
    await response.prepare(request)
    
    frame_count = 0
    try:
        while True:
            frame = await asyncio.get_event_loop().run_in_executor(
                None, camera_streamer.get_frame
            )
            if frame:
                frame_count += 1
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
    
    camera_status = "✅ Active (Pi Camera Module 3)" if (camera_streamer and camera_streamer.camera) else "❌ Not Available"
    
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
            <p><strong>Resolution:</strong> 1280x720 @ 30fps</p>
            <p><strong>Encoder:</strong> MJPEG</p>
        </div>
        """ if (camera_streamer and camera_streamer.camera) else """
        <div class="info">
            <p><strong>❌ Camera Not Available</strong></p>
            <p><strong>Troubleshooting:</strong></p>
            <ol style="text-align: left;">
                <li>Check camera connection: <code>libcamera-hello --list-cameras</code></li>
                <li>Stop other camera apps: <code>pkill libcamera-hello && pkill rpicam-hello</code></li>
                <li>Install packages: <code>sudo apt install -y python3-picamera2 python3-libcamera</code></li>
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
    if CAMERA_AVAILABLE and camera_streamer and camera_streamer.camera:
        print(f"   ✅ Camera Active")
        print(f"   Local: http://{local_ip}:8080/?action=stream")
        print(f"   View in browser: http://{local_ip}:8080/")
    else:
        print("   ❌ Camera Not Available")
        print("   Install: sudo apt install -y python3-picamera2 python3-libcamera")
        print("   Stop other apps: pkill libcamera-hello && pkill rpicam-hello")
        print("   Enable: sudo raspi-config -> Interface Options -> Camera")
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
