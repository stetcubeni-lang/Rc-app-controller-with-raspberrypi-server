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
    GPIO 18  - Throttle PWM (0-100%, speed for both directions)
    GPIO 19  - Direction Digital (HIGH = backward, LOW = forward, toggles once)
    GPIO 20  - Steering Right PWM (0-100%, right direction)
    GPIO 21  - Steering Left PWM (0-100%, left direction)
    GPIO 17  - Lights (Digital on/off)
    GPIO 27  - Auto Mode (Digital on/off)
    GPIO 22  - Brake PWM (0-100%)
    GPIO 23  - Honk (Digital, active when pressed)
    GPIO 25  - Gear 2 (Digital, active when selected)
    GPIO 26  - Gear 3 (Digital, active when selected)
    (Gear 1 is default - no pin needed)
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
import logging
import subprocess
import time
import shutil
import threading
import os
import sys
import tkinter as tk
from tkinter import ttk
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
THROTTLE_PWM_PIN = 18       # PWM: Throttle speed (0-100%, both directions)
DIRECTION_PIN = 19          # Digital: Direction (HIGH = backward, LOW = forward)
STEERING_RIGHT_PIN = 20     # PWM: Steering right (0-100%)
STEERING_LEFT_PIN = 21      # PWM: Steering left (0-100%)
LIGHTS_PIN = 17             # Digital: Lights on/off
AUTO_PIN = 27               # Digital: Auto mode on/off
BRAKE_PIN = 22              # PWM: Brake control (0-100%)
HONK_PIN = 23               # Digital: Honk (active when pressed)
GEAR_2_PIN = 25             # Digital: Gear 2 active
GEAR_3_PIN = 26             # Digital: Gear 3 active
# Gear 1 is default (no pin needed)
# ========================================

# PWM frequency (Hz)
PWM_FREQUENCY = 50

# Connected clients
connected_clients: Set[web.WebSocketResponse] = set()

# Live status table with Tkinter GUI
class StatusTable:
    """Displays a Tkinter window with a live-updating status table"""
    
    def __init__(self):
        self.initialized = False
        self.lock = threading.Lock()
        self.root = None
        self.value_labels = {}
        self.info_label = None
        self.values = {
            'throttle_pwm': 0.0,
            'direction': False,
            'steering_right': 0.0,
            'steering_left': 0.0,
            'brake': 0.0,
            'lights': False,
            'auto_mode': False,
            'honk': False,
            'gear': 1,
            'clients': 0,
            'camera': False,
        }
        self.server_info = {}
        self._gui_thread = None
    
    def init_table(self, camera_ok: bool, server_info: dict = None):
        """Start the Tkinter GUI in a separate thread"""
        self.values['camera'] = camera_ok
        if server_info:
            self.server_info = server_info
        self._gui_thread = threading.Thread(target=self._run_gui, daemon=True)
        self._gui_thread.start()
        self.initialized = True
    
    def _run_gui(self):
        """Create and run the Tkinter window"""
        self.root = tk.Tk()
        self.root.title("RC Car Server — Live Status")
        self.root.configure(bg='#1a1410')
        self.root.geometry('680x780')
        self.root.resizable(True, True)

        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Dark.TFrame', background='#1a1410')
        style.configure('Header.TLabel', background='#1a1410', foreground='#f59e0b',
                        font=('Consolas', 16, 'bold'))
        style.configure('SubHeader.TLabel', background='#1a1410', foreground='#fbbf24',
                        font=('Consolas', 11, 'bold'))
        style.configure('Cell.TLabel', background='#262016', foreground='#e2e8f0',
                        font=('Consolas', 10), padding=(8, 4))
        style.configure('CellHeader.TLabel', background='#332b1a', foreground='#f59e0b',
                        font=('Consolas', 10, 'bold'), padding=(8, 4))
        style.configure('ValueOn.TLabel', background='#262016', foreground='#22c55e',
                        font=('Consolas', 10, 'bold'), padding=(8, 4))
        style.configure('ValueOff.TLabel', background='#262016', foreground='#94a3b8',
                        font=('Consolas', 10), padding=(8, 4))
        style.configure('Info.TLabel', background='#1a1410', foreground='#94a3b8',
                        font=('Consolas', 9))
        style.configure('InfoHighlight.TLabel', background='#1a1410', foreground='#38bdf8',
                        font=('Consolas', 10, 'bold'))
        style.configure('Status.TLabel', background='#1a1410', foreground='#fbbf24',
                        font=('Consolas', 11))

        main_frame = ttk.Frame(self.root, style='Dark.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        ttk.Label(main_frame, text='\U0001F697  RC CAR — LIVE STATUS', style='Header.TLabel').pack(pady=(0, 10))

        # --- GPIO Table ---
        ttk.Label(main_frame, text='GPIO Outputs', style='SubHeader.TLabel').pack(anchor='w', pady=(4, 2))
        table_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        table_frame.pack(fill=tk.X, pady=(0, 8))

        headers = ['Output', 'Pin', 'Type', 'Value']
        for col, h in enumerate(headers):
            lbl = ttk.Label(table_frame, text=h, style='CellHeader.TLabel')
            lbl.grid(row=0, column=col, sticky='nsew', padx=1, pady=1)

        rows = [
            ('Throttle Speed',    f'GPIO {THROTTLE_PWM_PIN}',      'PWM',     'throttle_pwm'),
            ('Direction (BWD)',   f'GPIO {DIRECTION_PIN}',         'Digital', 'direction'),
            ('Steering Right',    f'GPIO {STEERING_RIGHT_PIN}',    'PWM',     'steering_right'),
            ('Steering Left',     f'GPIO {STEERING_LEFT_PIN}',     'PWM',     'steering_left'),
            ('Brake',             f'GPIO {BRAKE_PIN}',             'PWM',     'brake'),
            ('Lights',            f'GPIO {LIGHTS_PIN}',            'Digital', 'lights'),
            ('Auto Mode',         f'GPIO {AUTO_PIN}',              'Digital', 'auto_mode'),
            ('Honk',              f'GPIO {HONK_PIN}',              'Digital', 'honk'),
            ('Gear 1 (default)',  'No pin',                        'Default', 'gear_1'),
            ('Gear 2',            f'GPIO {GEAR_2_PIN}',            'Digital', 'gear_2'),
            ('Gear 3',            f'GPIO {GEAR_3_PIN}',            'Digital', 'gear_3'),
        ]

        for i, (name, pin, typ, key) in enumerate(rows, start=1):
            ttk.Label(table_frame, text=name, style='Cell.TLabel').grid(row=i, column=0, sticky='nsew', padx=1, pady=1)
            ttk.Label(table_frame, text=pin,  style='Cell.TLabel').grid(row=i, column=1, sticky='nsew', padx=1, pady=1)
            ttk.Label(table_frame, text=typ,  style='Cell.TLabel').grid(row=i, column=2, sticky='nsew', padx=1, pady=1)
            val_lbl = ttk.Label(table_frame, text=self._format_value(key), style='ValueOff.TLabel')
            val_lbl.grid(row=i, column=3, sticky='nsew', padx=1, pady=1)
            self.value_labels[key] = val_lbl

        for col in range(4):
            table_frame.columnconfigure(col, weight=1)

        # --- Status Bar ---
        ttk.Label(main_frame, text='Server Status', style='SubHeader.TLabel').pack(anchor='w', pady=(10, 2))
        self.status_label = ttk.Label(main_frame, text=self._format_status(), style='Status.TLabel')
        self.status_label.pack(anchor='w', pady=(0, 8))

        # --- Server Info ---
        ttk.Label(main_frame, text='Connection Info', style='SubHeader.TLabel').pack(anchor='w', pady=(6, 2))
        self.info_label = ttk.Label(main_frame, text=self._format_server_info(), style='Info.TLabel',
                                     justify=tk.LEFT, wraplength=640)
        self.info_label.pack(anchor='w', pady=(0, 4))

        if self.server_info.get('local_ip'):
            ip_frame = ttk.Frame(main_frame, style='Dark.TFrame')
            ip_frame.pack(anchor='w', pady=(2, 4))
            ttk.Label(ip_frame, text='Local: ', style='Info.TLabel').pack(side=tk.LEFT)
            ttk.Label(ip_frame, text=f"http://{self.server_info['local_ip']}:8765",
                      style='InfoHighlight.TLabel').pack(side=tk.LEFT)

        if self.server_info.get('ngrok_url'):
            ng_frame = ttk.Frame(main_frame, style='Dark.TFrame')
            ng_frame.pack(anchor='w', pady=(2, 4))
            ttk.Label(ng_frame, text='Ngrok: ', style='Info.TLabel').pack(side=tk.LEFT)
            ttk.Label(ng_frame, text=self.server_info['ngrok_url'],
                      style='InfoHighlight.TLabel').pack(side=tk.LEFT)

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.mainloop()

    def _on_close(self):
        """Handle window close — exit the whole app"""
        self.root.destroy()
        os._exit(0)

    def _format_value(self, key: str) -> str:
        v = self.values
        if key == 'throttle_pwm': return f"{v['throttle_pwm']:.1f}%"
        if key == 'direction':    return 'BWD' if v['direction'] else 'FWD'
        if key == 'steering_right': return f"{v['steering_right']:.1f}%"
        if key == 'steering_left':  return f"{v['steering_left']:.1f}%"
        if key == 'brake':          return f"{v['brake']:.1f}%"
        if key == 'lights':         return 'ON' if v['lights'] else 'OFF'
        if key == 'auto_mode':      return 'ON' if v['auto_mode'] else 'OFF'
        if key == 'honk':           return 'ON' if v['honk'] else 'OFF'
        if key == 'gear_1':         return 'ON' if v['gear'] == 1 else 'OFF'
        if key == 'gear_2':         return 'ON' if v['gear'] == 2 else 'OFF'
        if key == 'gear_3':         return 'ON' if v['gear'] == 3 else 'OFF'
        return ''

    def _value_style(self, key: str) -> str:
        v = self.values
        if key in ('throttle_pwm', 'steering_right', 'steering_left', 'brake'):
            return 'ValueOn.TLabel' if v.get(key, 0) > 0 else 'ValueOff.TLabel'
        if key == 'direction':  return 'ValueOn.TLabel' if v['direction'] else 'ValueOff.TLabel'
        if key == 'lights':    return 'ValueOn.TLabel' if v['lights'] else 'ValueOff.TLabel'
        if key == 'auto_mode': return 'ValueOn.TLabel' if v['auto_mode'] else 'ValueOff.TLabel'
        if key == 'honk':      return 'ValueOn.TLabel' if v['honk'] else 'ValueOff.TLabel'
        if key == 'gear_1':    return 'ValueOn.TLabel' if v['gear'] == 1 else 'ValueOff.TLabel'
        if key == 'gear_2':    return 'ValueOn.TLabel' if v['gear'] == 2 else 'ValueOff.TLabel'
        if key == 'gear_3':    return 'ValueOn.TLabel' if v['gear'] == 3 else 'ValueOff.TLabel'
        return 'ValueOff.TLabel'

    def _format_status(self) -> str:
        v = self.values
        cam = 'Active' if v['camera'] else 'Off'
        return f"Clients: {v['clients']}    Camera: {cam}    Gear: {v['gear']}"

    def _format_server_info(self) -> str:
        info = self.server_info
        lines = []
        lines.append(f"Port: 8765 (HTTP + WebSocket combined)")
        if info.get('gpio'):
            lines.append(f"GPIO: Hardware control enabled")
        else:
            lines.append(f"GPIO: Simulation mode (no lgpio)")
        if info.get('camera'):
            lines.append(f"Camera: libcamera-vid active (640x480 @ 30fps)")
        else:
            lines.append(f"Camera: Not available")
        return '\n'.join(lines)

    def _refresh_gui(self):
        """Update all labels in the GUI (must be called from GUI thread)"""
        for key, lbl in self.value_labels.items():
            lbl.configure(text=self._format_value(key), style=self._value_style(key))
        if self.status_label:
            self.status_label.configure(text=self._format_status())

    def update(self, key: str, value):
        """Update a value and schedule GUI refresh"""
        with self.lock:
            self.values[key] = value
            if self.initialized and self.root:
                try:
                    self.root.after_idle(self._refresh_gui)
                except Exception:
                    pass

status_table = StatusTable()

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
        self.throttle_duty = 0
        self.direction_active = False
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
            lgpio.gpio_claim_output(self.gpio_chip, THROTTLE_PWM_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, DIRECTION_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, STEERING_RIGHT_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, STEERING_LEFT_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, LIGHTS_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, AUTO_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, BRAKE_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, HONK_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, GEAR_2_PIN)
            lgpio.gpio_claim_output(self.gpio_chip, GEAR_3_PIN)
            
            # ALL pins LOW on startup
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_PWM_PIN, PWM_FREQUENCY, 0)
            lgpio.gpio_write(self.gpio_chip, DIRECTION_PIN, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 0)
            lgpio.gpio_write(self.gpio_chip, LIGHTS_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, AUTO_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, GEAR_2_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, GEAR_3_PIN, 0)
            
            logger.info("GPIO initialized successfully on gpiochip4 (Pi 5)")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            self.gpio_chip = None
    
    def _update_auto_brake(self, throttle_percentage: float):
        """Auto brake: ON when throttle is 0%, OFF when throttle > 0%"""
        if throttle_percentage == 0 and self.brake_duty == 0:
            self.brake_duty = 100
            status_table.update('brake', 100)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 100)
                logger.info("Auto Brake -> ON (throttle is 0%)")
        elif throttle_percentage > 0 and self.brake_duty > 0:
            self.brake_duty = 0
            status_table.update('brake', 0)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 0)
                logger.info("Auto Brake -> OFF (throttle active)")

    def set_throttle_forward(self, percentage: float):
        duty_cycle = percentage
        self.throttle_duty = duty_cycle
        status_table.update('throttle_pwm', duty_cycle)
        
        self._update_auto_brake(percentage)
        
        if percentage > 0 and self.direction_active:
            self.direction_active = False
            status_table.update('direction', False)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.gpio_write(self.gpio_chip, DIRECTION_PIN, 0)
                logger.info("Direction PIN -> LOW (forward)")
        
        if not self.direction_active and GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_PWM_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_throttle_backward(self, percentage: float):
        duty_cycle = percentage
        self.throttle_duty = duty_cycle
        status_table.update('throttle_pwm', duty_cycle)
        
        self._update_auto_brake(percentage)
        
        if percentage > 0 and not self.direction_active:
            self.direction_active = True
            status_table.update('direction', True)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.gpio_write(self.gpio_chip, DIRECTION_PIN, 1)
                logger.info("Direction PIN -> HIGH (backward) [activated once]")
        elif percentage == 0 and self.direction_active:
            self.direction_active = False
            status_table.update('direction', False)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.gpio_write(self.gpio_chip, DIRECTION_PIN, 0)
                logger.info("Direction PIN -> LOW (stopped) [deactivated once]")
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_PWM_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_steering_right(self, percentage: float):
        status_table.update('steering_right', percentage)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            duty_cycle = percentage
            self.steering_right_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_steering_left(self, percentage: float):
        status_table.update('steering_left', percentage)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            duty_cycle = percentage
            self.steering_left_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_gear(self, gear: int):
        if 1 <= gear <= 3:
            self.current_gear = gear
            status_table.update('gear', gear)
            if GPIO_AVAILABLE and self.gpio_chip is not None:
                lgpio.gpio_write(self.gpio_chip, GEAR_2_PIN, 1 if gear == 2 else 0)
                lgpio.gpio_write(self.gpio_chip, GEAR_3_PIN, 1 if gear == 3 else 0)
    
    def set_lights(self, on: bool):
        self.lights_on = on
        status_table.update('lights', on)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, LIGHTS_PIN, 1 if on else 0)
    
    def set_auto_mode(self, on: bool):
        self.auto_mode = on
        status_table.update('auto_mode', on)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, AUTO_PIN, 1 if on else 0)
    
    def set_brake(self, percentage: float):
        status_table.update('brake', percentage)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            duty_cycle = (percentage / 100) * 100
            self.brake_duty = duty_cycle
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, duty_cycle)
    
    def set_honk(self, active: bool):
        self.honk_active = active
        status_table.update('honk', active)
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 1 if active else 0)
    
    def set_all_low(self):
        """Set ALL pins to LOW (safe state)"""
        self.throttle_duty = 0
        self.direction_active = False
        self.steering_right_duty = 0
        self.steering_left_duty = 0
        self.brake_duty = 0
        self.lights_on = False
        self.auto_mode = False
        self.honk_active = False
        self.current_gear = 1
        
        status_table.update('throttle_pwm', 0)
        status_table.update('direction', False)
        status_table.update('steering_right', 0)
        status_table.update('steering_left', 0)
        status_table.update('brake', 0)
        status_table.update('lights', False)
        status_table.update('auto_mode', False)
        status_table.update('honk', False)
        status_table.update('gear', 1)
        
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            lgpio.tx_pwm(self.gpio_chip, THROTTLE_PWM_PIN, PWM_FREQUENCY, 0)
            lgpio.gpio_write(self.gpio_chip, DIRECTION_PIN, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_RIGHT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, STEERING_LEFT_PIN, PWM_FREQUENCY, 0)
            lgpio.tx_pwm(self.gpio_chip, BRAKE_PIN, PWM_FREQUENCY, 0)
            lgpio.gpio_write(self.gpio_chip, LIGHTS_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, AUTO_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, HONK_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, GEAR_2_PIN, 0)
            lgpio.gpio_write(self.gpio_chip, GEAR_3_PIN, 0)
            logger.info("All pins set to LOW")
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if GPIO_AVAILABLE and self.gpio_chip is not None:
            self.set_all_low()
            
            lgpio.gpio_free(self.gpio_chip, THROTTLE_PWM_PIN)
            lgpio.gpio_free(self.gpio_chip, DIRECTION_PIN)
            lgpio.gpio_free(self.gpio_chip, STEERING_RIGHT_PIN)
            lgpio.gpio_free(self.gpio_chip, STEERING_LEFT_PIN)
            lgpio.gpio_free(self.gpio_chip, LIGHTS_PIN)
            lgpio.gpio_free(self.gpio_chip, AUTO_PIN)
            lgpio.gpio_free(self.gpio_chip, BRAKE_PIN)
            lgpio.gpio_free(self.gpio_chip, HONK_PIN)
            lgpio.gpio_free(self.gpio_chip, GEAR_2_PIN)
            lgpio.gpio_free(self.gpio_chip, GEAR_3_PIN)
            
            lgpio.gpiochip_close(self.gpio_chip)
            logger.info("GPIO cleanup completed")

# Initialize RC car controller
rc_car = RCCarController()

async def websocket_handler(request):
    """Handle WebSocket client connection using aiohttp"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    client_address = request.remote
    connected_clients.add(ws)
    status_table.update('clients', len(connected_clients))
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
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
                    logger.error(f"Invalid JSON received: {msg.data}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f'WebSocket error: {ws.exception()}')
    finally:
        connected_clients.discard(ws)
        status_table.update('clients', len(connected_clients))
        rc_car.set_all_low()
    
    return ws

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
        <img src="/camera" alt="Pi Camera Module 3 Stream" />
        <div class="info">
            <p><strong>Stream URL for Mobile App:</strong></p>
            <p><code>http://YOUR_PI_IP:8765/camera</code></p>
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

async def start_combined_server():
    """Start combined HTTP/WebSocket server on port 8765"""
    app = web.Application()
    app.router.add_get('/camera', stream_handler)
    app.router.add_get('/camera-info', root_handler)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_get('/', root_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8765)
    await site.start()
    
    logger.info("📹 Combined HTTP/WebSocket Server started on port 8765")
    
    return runner

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
        
        # Start ngrok in background for port 8765 (handles both WebSocket and HTTP camera)
        ngrok_process = subprocess.Popen(
            ['ngrok', 'http', '8765', '--host-header=rewrite', '--request-header-add=ngrok-skip-browser-warning:true'],
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
    """Start combined HTTP/WebSocket server"""
    # Get local IP address
    import socket
    
    def get_local_ip():
        """Get the actual local network IP address (not localhost)"""
        try:
            # Create a socket to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            try:
                # Connect to external address (doesn't actually send data)
                s.connect(('10.254.254.254', 1))
                local_ip = s.getsockname()[0]
            except Exception:
                # Fallback: try to get from hostname
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                # If we got localhost, try another method
                if local_ip.startswith('127.'):
                    # Get all network interfaces
                    import subprocess
                    result = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
                    if result.returncode == 0 and result.stdout.strip():
                        # Get first non-localhost IP
                        ips = result.stdout.strip().split()
                        for ip in ips:
                            if not ip.startswith('127.') and ':' not in ip:  # Avoid IPv6
                                return ip
            finally:
                s.close()
            return local_ip
        except Exception as e:
            logger.error(f"Failed to get local IP: {e}")
            return "unknown"
    
    local_ip = get_local_ip()
    
    # Start combined server
    runner = await start_combined_server()
    
    # Start ngrok tunnel
    ngrok_url = await start_ngrok()
    
    camera_ok = CAMERA_AVAILABLE and camera_streamer and camera_streamer.camera_process is not None

    server_info = {
        'local_ip': local_ip,
        'ngrok_url': ngrok_url,
        'gpio': GPIO_AVAILABLE,
        'camera': camera_ok,
    }

    logger.info(f"Server running on http://{local_ip}:8765")
    if ngrok_url:
        logger.info(f"ngrok tunnel: {ngrok_url}")
    logging.disable(logging.CRITICAL)

    status_table.init_table(camera_ok, server_info)
    
    # Keep server running
    try:
        await asyncio.Future()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Server stopped by user")
    finally:
        rc_car.cleanup()
        if camera_streamer:
            camera_streamer.cleanup()
