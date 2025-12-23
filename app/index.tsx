import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Dimensions,
  TextInput,
  Modal,
  Platform,
  Animated,
  PanResponder,
} from "react-native";
import { WebView } from 'react-native-webview';
import { Image } from 'expo-image';
import { GestureDetector, Gesture } from 'react-native-gesture-handler';
import { LinearGradient } from "expo-linear-gradient";
import { Zap, Video, Settings as SettingsIcon, Maximize2 } from "lucide-react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get("window");

type Gear = 1 | 2 | 3;

const DEFAULT_IP = "";

export default function RCCarController() {
  const insets = useSafeAreaInsets();
  const [throttle, setThrottle] = useState<number>(0);
  const [brake, setBrake] = useState<number>(0);
  const [steering, setSteering] = useState<number>(0);
  const [gear, setGear] = useState<Gear>(1);
  const [honkPressed, setHonkPressed] = useState<boolean>(false);
  const [lightsOn, setLightsOn] = useState<boolean>(false);
  const [autoMode, setAutoMode] = useState<boolean>(false);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [connectionError, setConnectionError] = useState<string>("");
  const [piIP, setPiIP] = useState<string>(DEFAULT_IP);
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const [tempIP, setTempIP] = useState<string>(DEFAULT_IP);
  const [connectionAttempts, setConnectionAttempts] = useState<number>(0);
  const [cameraPosition, setCameraPosition] = useState({ x: 20, y: 120 });
  const [cameraSize, setCameraSize] = useState({ width: width * 0.75, height: (width * 0.75) * (9/16) });
  const [hasLoadedCameraSettings, setHasLoadedCameraSettings] = useState(false);
  const [cameraError, setCameraError] = useState(false);
  const [cameraKey, setCameraKey] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadSavedIP();
    loadCameraSettings();
  }, []);

  useEffect(() => {
    if (!piIP) {
      setShowSettings(true);
    }
  }, [piIP]);

  const loadSavedIP = async () => {
    try {
      const savedIP = await AsyncStorage.getItem('raspberry_pi_ip');
      if (savedIP) {
        console.log(`Loaded saved IP: ${savedIP}`);
        setPiIP(savedIP);
        setTempIP(savedIP);
      }
    } catch (error) {
      console.error('Failed to load saved IP:', error);
    }
  };

  const saveIP = async (ip: string) => {
    try {
      await AsyncStorage.setItem('raspberry_pi_ip', ip);
      console.log(`Saved IP: ${ip}`);
    } catch (error) {
      console.error('Failed to save IP:', error);
    }
  };

  const loadCameraSettings = async () => {
    try {
      const savedPosition = await AsyncStorage.getItem('camera_position');
      const savedSize = await AsyncStorage.getItem('camera_size');
      
      if (savedPosition) {
        const pos = JSON.parse(savedPosition);
        setCameraPosition(pos);
        console.log('Loaded camera position:', pos);
      }
      
      if (savedSize) {
        const size = JSON.parse(savedSize);
        setCameraSize(size);
        console.log('Loaded camera size:', size);
      }
      
      setHasLoadedCameraSettings(true);
    } catch (error) {
      console.error('Failed to load camera settings:', error);
      setHasLoadedCameraSettings(true);
    }
  };

  const saveCameraPosition = async (pos: { x: number; y: number }) => {
    try {
      await AsyncStorage.setItem('camera_position', JSON.stringify(pos));
      console.log('Saved camera position:', pos);
    } catch (error) {
      console.error('Failed to save camera position:', error);
    }
  };

  const saveCameraSize = async (size: { width: number; height: number }) => {
    try {
      await AsyncStorage.setItem('camera_size', JSON.stringify(size));
      console.log('Saved camera size:', size);
    } catch (error) {
      console.error('Failed to save camera size:', error);
    }
  };

  const connectToServer = useCallback(() => {
    if (!piIP || piIP.trim() === "") {
      setConnectionError("Please set Raspberry Pi IP address in settings");
      return;
    }

    if (wsRef.current?.readyState === WebSocket.CONNECTING || 
        wsRef.current?.readyState === WebSocket.OPEN) {
      console.log('Already connected or connecting...');
      return;
    }

    if (reconnectTimeoutRef.current) {
      console.log('Connection attempt already scheduled');
      return;
    }

    try {
      let cleanIP = piIP.trim();
      cleanIP = cleanIP.replace(/^(https?:\/\/)/i, '');
      cleanIP = cleanIP.replace(/^(wss?:\/\/)/i, '');
      cleanIP = cleanIP.replace(/\/+$/, '');
      
      let url: string;
      
      if (cleanIP.includes('.ngrok-free.dev') || cleanIP.includes('.ngrok-free.app') || cleanIP.includes('.ngrok.')) {
        cleanIP = cleanIP.replace(/:\d+$/, '');
        url = `wss://${cleanIP}`;
        console.log(`🔒 Detected ngrok URL, using secure WSS: ${url}`);
      } else if (cleanIP.includes(':')) {
        url = `ws://${cleanIP}`;
      } else {
        url = `ws://${cleanIP}:8765`;
      }
      setConnectionAttempts(prev => {
        console.log(`🔄 Attempt ${prev + 1}: Connecting to ${url}`);
        return prev + 1;
      });
      
      const ws = new WebSocket(url);
      
      ws.onopen = () => {
        console.log("✅ Connected to RC car server");
        setIsConnected(true);
        setConnectionError("");
        setConnectionAttempts(0);
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          if (typeof event.data === 'string' && event.data.trim().startsWith('{')) {
            const data = JSON.parse(event.data);
            console.log('Received from server:', data);
          } else {
            console.log('Received non-JSON message:', event.data);
          }
        } catch (error) {
          console.error('Error parsing message:', error, 'Raw data:', event.data);
        }
      };

      ws.onclose = (event) => {
        console.log(`❌ Disconnected - Code: ${event.code}, Reason: ${event.reason || 'none'}`);
        setIsConnected(false);
        
        if (event.code === 1006) {
          if (cleanIP.includes('.ngrok')) {
            setConnectionError("ngrok connection failed. Is Python server running?");
          } else {
            setConnectionError("Connection failed. Is the server running?");
          }
        } else if (event.code === 1000) {
          setConnectionError("Connection closed normally");
        } else {
          setConnectionError(`Connection closed (code: ${event.code})`);
        }
        
        setConnectionAttempts(currentAttempts => {
          if (!reconnectTimeoutRef.current && currentAttempts < 5) {
            const backoffDelay = Math.min(3000 + (currentAttempts * 2000), 15000);
            console.log(`⏳ Reconnecting in ${backoffDelay/1000}s...`);
            reconnectTimeoutRef.current = setTimeout(() => {
              reconnectTimeoutRef.current = null;
              connectToServer();
            }, backoffDelay);
          } else if (currentAttempts >= 5) {
            setConnectionError("Failed after 5 attempts. Check settings and restart server.");
            console.log("❌ Max reconnection attempts reached. Please check:");
            console.log("   1. Is Python server running?");
            console.log("   2. Is ngrok running with: ngrok http 8765 --host-header=rewrite");
            console.log("   3. Is the hostname correct in settings?");
          }
          return currentAttempts;
        });
      };

      ws.onerror = (error: any) => {
        const errorDetails = {
          message: error.message || 'Connection failed',
          type: error.type || 'error',
          url: url
        };
        
        console.error(`❌ WebSocket error: ${errorDetails.type}`);
        console.error(`   Message: ${errorDetails.message}`);
        console.error(`   URL: ${url}`);
        
        let errorMessage = 'Connection failed';
        if (cleanIP.includes('.ngrok')) {
          errorMessage = 'Unable to connect to ngrok server';
          console.error(`   💡 Troubleshooting steps:`);
          console.error(`   1. Make sure Python server is running on Pi: python3 raspberry-pi-server.py`);
          console.error(`   2. Check ngrok is running: ngrok http 8765 --host-header=rewrite`);
          console.error(`   3. Verify ngrok URL in settings matches tunnel URL`);
          console.error(`   4. Try regenerating ngrok tunnel (restart ngrok)`);
        } else {
          console.error(`   💡 Troubleshooting steps:`);
          console.error(`   1. Verify Python server is running: python3 raspberry-pi-server.py`);
          console.error(`   2. Check devices are on same WiFi network`);
          console.error(`   3. Verify IP address is correct: hostname -I`);
        }
        
        setConnectionError(errorMessage);
        setIsConnected(false);
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("Failed to create WebSocket:", error);
      setIsConnected(false);
      setConnectionError("Failed to create connection");
    }
  }, [piIP]);

  const disconnectFromServer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionAttempts(0);
  }, []);

  useEffect(() => {
    if (piIP && !isConnected && !reconnectTimeoutRef.current) {
      connectToServer();
    }
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [piIP, connectToServer]);

  const handleSaveSettings = () => {
    const trimmedIP = tempIP.trim();
    if (!trimmedIP) {
      setConnectionError("IP address cannot be empty");
      return;
    }
    
    disconnectFromServer();
    setPiIP(trimmedIP);
    saveIP(trimmedIP);
    setShowSettings(false);
    setConnectionAttempts(0);
    
    setTimeout(() => {
      connectToServer();
    }, 500);
  };

  const sendCommand = (type: string, value: number | boolean) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const message = JSON.stringify({ type, value, gear, lights: lightsOn, auto: autoMode });
      wsRef.current.send(message);
      console.log(`Sent: ${type} = ${value}`);
    }
  };

  const handleThrottleChange = (value: number) => {
    setThrottle(value);
    if (value >= 0) {
      sendCommand("throttle_forward", value);
      sendCommand("throttle_backward", 0);
    } else {
      sendCommand("throttle_forward", 0);
      sendCommand("throttle_backward", Math.abs(value));
    }
  };

  const handleBrakeChange = (value: number) => {
    setBrake(value);
    sendCommand("brake", value);
  };

  const handleSteeringChange = (value: number) => {
    setSteering(value);
    if (value >= 0) {
      sendCommand("steering_right", value);
      sendCommand("steering_left", 0);
    } else {
      sendCommand("steering_right", 0);
      sendCommand("steering_left", Math.abs(value));
    }
  };

  const handleHonkPress = () => {
    setHonkPressed(true);
    sendCommand("honk", true);
  };

  const handleHonkRelease = () => {
    setHonkPressed(false);
    sendCommand("honk", false);
  };

  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const message = JSON.stringify({ 
        type: "settings", 
        gear, 
        lights: lightsOn,
        auto: autoMode
      });
      wsRef.current.send(message);
    }
  }, [gear, lightsOn, autoMode]);

  return (
    <LinearGradient
      colors={["#1a1410", "#2d1810", "#1a1410"]}
      style={styles.container}
    >
        <View style={[styles.safeArea, { paddingTop: insets.top }]}>
        <View style={styles.statusBar}>
          <View style={styles.statusBarContent}>
            <View style={styles.statusBarRow}>
              <View style={styles.connectionStatus}>
                <View
                  style={[
                    styles.statusDot,
                    { backgroundColor: isConnected ? "#10b981" : "#ef4444" },
                  ]}
                />
                <Text style={styles.statusText}>
                  {isConnected ? "CONNECTED" : "DISCONNECTED"}
                </Text>
              </View>
              <Pressable
                onPress={() => setShowSettings(true)}
                style={styles.settingsButton}
              >
                <SettingsIcon size={20} color="#f59e0b" />
              </Pressable>
            </View>
            {!isConnected && connectionError && (
              <View style={styles.errorContainer}>
                <Text style={styles.errorText}>{connectionError}</Text>
                <Text style={styles.errorHint}>
                  Trying: {(() => {
                    let cleanIP = piIP.trim().replace(/^(https?:\/\/)/i, '').replace(/^(wss?:\/\/)/i, '').replace(/\/+$/, '');
                    if (cleanIP.includes('.ngrok-free.dev') || cleanIP.includes('.ngrok-free.app') || cleanIP.includes('.ngrok.')) {
                      const host = cleanIP.replace(/:\d+$/, '');
                      return `wss://${host}`;
                    } else if (!cleanIP.includes(':')) {
                      return `ws://${cleanIP}:8765`;
                    }
                    return `ws://${cleanIP}`;
                  })()}
                </Text>
                {connectionAttempts > 0 && (
                  <Text style={styles.errorHint}>
                    Attempts: {connectionAttempts}/5
                  </Text>
                )}
                {piIP.includes('.ngrok') && (
                  <View style={styles.troubleshootingContainer}>
                    <Text style={[styles.errorHint, { color: '#fca5a5', fontWeight: '700' as const }]}>
                      Troubleshooting:
                    </Text>
                    <Text style={[styles.errorHint, { color: '#fca5a5' }]}>
                      1. Python server running: python3 raspberry-pi-server.py
                    </Text>
                    <Text style={[styles.errorHint, { color: '#fca5a5' }]}>
                      2. ngrok running: ngrok http 8765 --host-header=rewrite
                    </Text>
                    <Text style={[styles.errorHint, { color: '#fca5a5' }]}>
                      3. Check ngrok shows &quot;online&quot; status
                    </Text>
                    <Text style={[styles.errorHint, { color: '#fca5a5' }]}>
                      4. Try restarting both server and ngrok
                    </Text>
                  </View>
                )}
              </View>
            )}

          </View>
        </View>

        <Modal
          visible={showSettings}
          transparent
          animationType="fade"
          onRequestClose={() => setShowSettings(false)}
        >
          <Pressable 
            style={styles.modalOverlay}
            onPress={() => setShowSettings(false)}
          >
            <Pressable 
              style={styles.modalContent}
              onPress={(e) => e.stopPropagation()}
            >
              <Text style={styles.modalTitle}>SERVER SETTINGS</Text>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>Raspberry Pi IP Address</Text>
                <TextInput
                  style={styles.input}
                  value={tempIP}
                  onChangeText={setTempIP}
                  placeholder="e.g. 192.168.1.100 or 2001:db8::1"
                  placeholderTextColor="#78716c"
                  keyboardType={Platform.OS === 'ios' ? 'numbers-and-punctuation' : 'default'}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>

              <View style={styles.helpContainer}>
                <Text style={styles.helpTitle}>Local Network (Same WiFi):</Text>
                <Text style={styles.helpText}>1. On Pi, run: hostname -I</Text>
                <Text style={styles.helpText}>2. Use that IP (e.g., 192.168.1.100)</Text>
                <Text style={styles.helpText}>3. Ensure both devices on same WiFi</Text>
                <Text style={[styles.helpText, { color: '#ef4444', fontWeight: '700' as const, marginTop: 4 }]}>⚠️ Don&apos;t use localhost or 127.0.0.1 - won&apos;t work on mobile!</Text>
                
                <Text style={[styles.helpTitle, { marginTop: 12 }]}>Remote Access (ngrok):</Text>
                <Text style={styles.helpText}>1. On Pi: python3 raspberry-pi-server.py</Text>
                <Text style={[styles.helpText, { color: '#f59e0b', fontWeight: '700' as const }]}>2. New terminal: ngrok http 8765 --host-header=rewrite</Text>
                <Text style={styles.helpText}>3. Wait for &quot;Session Status: online&quot;</Text>
                <Text style={styles.helpText}>4. Copy ONLY hostname from Forwarding line</Text>
                <Text style={styles.helpText}>Example: abc123.ngrok-free.app</Text>
                <Text style={[styles.helpText, { color: '#ef4444', fontWeight: '700' as const, marginTop: 4 }]}>⚠️ No https://, no ws://, no port!</Text>
                <Text style={[styles.helpText, { color: '#10b981', fontWeight: '700' as const }]}>✅ Camera works with ngrok too!</Text>
              </View>

              <View style={styles.modalButtons}>
                <Pressable
                  style={styles.modalButton}
                  onPress={() => {
                    setTempIP(piIP);
                    setShowSettings(false);
                  }}
                >
                  <Text style={styles.modalButtonText}>CANCEL</Text>
                </Pressable>
                <Pressable
                  style={[styles.modalButton, styles.modalButtonPrimary]}
                  onPress={handleSaveSettings}
                >
                  <Text style={[styles.modalButtonText, styles.modalButtonTextPrimary]}>
                    SAVE & CONNECT
                  </Text>
                </Pressable>
              </View>
            </Pressable>
          </Pressable>
        </Modal>

        <View style={styles.topControls}>
          <View style={styles.gearSection}>
            <Text style={styles.sectionLabel}>GEAR</Text>
            <View style={styles.gearButtons}>
              {([1, 2, 3] as Gear[]).map((g) => (
                <Pressable
                  key={g}
                  onPress={() => setGear(g)}
                  style={[
                    styles.gearButton,
                    gear === g && styles.gearButtonActive,
                  ]}
                >
                  <Text
                    style={[
                      styles.gearButtonText,
                      gear === g && styles.gearButtonTextActive,
                    ]}
                  >
                    {g}
                  </Text>
                </Pressable>
              ))}
            </View>
            
            <Pressable
              onPressIn={handleHonkPress}
              onPressOut={handleHonkRelease}
              style={[styles.honkButton, honkPressed && styles.honkButtonActive]}
            >
              <Text
                style={[
                  styles.honkButtonText,
                  honkPressed && styles.honkButtonTextActive,
                ]}
              >
                🔊 HONK
              </Text>
            </Pressable>
          </View>

          <View style={styles.toggleButtonsContainer}>
            <Pressable
              onPress={() => setLightsOn(!lightsOn)}
              style={[styles.toggleButton, lightsOn && styles.toggleButtonActive]}
            >
              <Zap
                size={24}
                color={lightsOn ? "#1a1410" : "#f59e0b"}
                fill={lightsOn ? "#f59e0b" : "none"}
              />
              <Text
                style={[
                  styles.toggleButtonText,
                  lightsOn && styles.toggleButtonTextActive,
                ]}
              >
                LIGHTS
              </Text>
            </Pressable>
            
            <Pressable
              onPress={() => setAutoMode(!autoMode)}
              style={[styles.toggleButton, autoMode && styles.toggleButtonActive]}
            >
              <Zap
                size={24}
                color={autoMode ? "#1a1410" : "#f59e0b"}
                fill={autoMode ? "#f59e0b" : "none"}
              />
              <Text
                style={[
                  styles.toggleButtonText,
                  autoMode && styles.toggleButtonTextActive,
                ]}
              >
                AUTO
              </Text>
            </Pressable>
          </View>
        </View>

        {hasLoadedCameraSettings && piIP && (
          <DraggableResizableCamera 
              piIP={piIP}
              position={cameraPosition}
              onPositionChange={(pos) => {
                setCameraPosition(pos);
                saveCameraPosition(pos);
              }}
              size={cameraSize}
              onSizeChange={(size) => {
                setCameraSize(size);
                saveCameraSize(size);
              }}
              cameraError={cameraError}
              onCameraError={setCameraError}
              cameraKey={cameraKey}
              onRefresh={() => setCameraKey(prev => prev + 1)}
              isFullscreen={isFullscreen}
              onFullscreenChange={setIsFullscreen}
            />
        )}

        <View style={styles.mainControls}>
          <ThrottleSlider value={throttle} onChange={handleThrottleChange} />
          <View style={styles.rightControls}>
            <BrakeSlider value={brake} onChange={handleBrakeChange} />
            <SteeringSlider value={steering} onChange={handleSteeringChange} />
          </View>
        </View>
        </View>
      </LinearGradient>
  );
}

interface SliderProps {
  value: number;
  onChange: (value: number) => void;
}

function ThrottleSlider({ value, onChange }: SliderProps) {
  const sliderHeight = height * 0.45;
  const sliderRef = useRef<View>(null);
  const sliderBounds = useRef({ x: 0, y: 0, width: 60, height: sliderHeight });
  const startY = useRef(0);

  const panGesture = Gesture.Pan()
    .runOnJS(true)
    .onBegin((event) => {
      startY.current = event.y;
      const y = event.y;
      const percentage = Math.max(
        -100,
        Math.min(100, ((sliderHeight / 2 - y) / (sliderHeight / 2)) * 100)
      );
      onChange(percentage);
      console.log(`[Throttle] Gesture started`);
    })
    .onUpdate((event) => {
      const y = event.y;
      const percentage = Math.max(
        -100,
        Math.min(100, ((sliderHeight / 2 - y) / (sliderHeight / 2)) * 100)
      );
      onChange(percentage);
    })
    .onEnd(() => {
      console.log(`[Throttle] Gesture ended`);
      onChange(0);
    })
    .onFinalize(() => {
      onChange(0);
    });

  return (
    <View style={styles.throttleContainer}>
      <Text style={styles.sliderLabel}>THROTTLE</Text>
      <GestureDetector gesture={panGesture}>
        <View
          ref={sliderRef}
          style={[styles.verticalSlider, { height: sliderHeight }]}
          onLayout={(event) => {
            sliderRef.current?.measureInWindow((pageX, pageY) => {
              sliderBounds.current = { x: pageX, y: pageY, width: 60, height: sliderHeight };
              console.log(`[Throttle] Layout bounds:`, sliderBounds.current);
            });
          }}
        >
        <View style={styles.sliderCenter} />
        <View
          pointerEvents="none"
          style={[
            styles.sliderThumb,
            {
              top:
                sliderHeight / 2 - (value / 100) * (sliderHeight / 2) - 20,
            },
          ]}
        >
          <LinearGradient
            colors={value > 0 ? ["#f59e0b", "#d97706"] : ["#ef4444", "#dc2626"]}
            style={styles.thumbGradient}
          />
        </View>
        </View>
      </GestureDetector>
      <View style={styles.sliderLabels}>
        <Text style={styles.sliderLabelText}>FWD</Text>
        <Text style={styles.sliderLabelText}>BWD</Text>
      </View>
    </View>
  );
}

function BrakeSlider({ value, onChange }: SliderProps) {
  const sliderWidth = width * 0.45;
  const sliderRef = useRef<View>(null);
  const sliderBounds = useRef({ x: 0, y: 0, width: sliderWidth, height: 60 });

  const panGesture = Gesture.Pan()
    .runOnJS(true)
    .onBegin((event) => {
      const x = event.x;
      const percentage = Math.max(
        0,
        Math.min(100, (x / sliderWidth) * 100)
      );
      onChange(percentage);
      console.log(`[Brake] Gesture started`);
    })
    .onUpdate((event) => {
      const x = event.x;
      const percentage = Math.max(
        0,
        Math.min(100, (x / sliderWidth) * 100)
      );
      onChange(percentage);
    })
    .onEnd(() => {
      console.log(`[Brake] Gesture ended`);
      onChange(0);
    })
    .onFinalize(() => {
      onChange(0);
    });

  return (
    <View style={styles.brakeContainer}>
      <Text style={styles.sliderLabel}>BRAKE</Text>
      <GestureDetector gesture={panGesture}>
        <View
          ref={sliderRef}
          style={[styles.horizontalSlider, { width: sliderWidth }]}
          onLayout={(event) => {
            sliderRef.current?.measureInWindow((pageX, pageY) => {
              sliderBounds.current = { x: pageX, y: pageY, width: sliderWidth, height: 60 };
              console.log(`[Brake] Layout bounds:`, sliderBounds.current);
            });
          }}
        >
        <View
          pointerEvents="none"
          style={[
            styles.sliderThumb,
            {
              left: (value / 100) * sliderWidth - 20,
            },
          ]}
        >
          <LinearGradient
            colors={["#ef4444", "#dc2626"]}
            style={styles.thumbGradient}
          />
        </View>
        </View>
      </GestureDetector>
      <View style={styles.sliderLabelsHorizontal}>
        <Text style={styles.sliderLabelText}>0%</Text>
        <Text style={styles.sliderLabelText}>100%</Text>
      </View>
    </View>
  );
}

function SteeringSlider({ value, onChange }: SliderProps) {
  const sliderWidth = width * 0.45;
  const sliderRef = useRef<View>(null);
  const sliderBounds = useRef({ x: 0, y: 0, width: sliderWidth, height: 60 });

  const panGesture = Gesture.Pan()
    .runOnJS(true)
    .onBegin((event) => {
      const x = event.x;
      const percentage = Math.max(
        -100,
        Math.min(100, ((x - sliderWidth / 2) / (sliderWidth / 2)) * 100)
      );
      onChange(percentage);
      console.log(`[Steering] Gesture started`);
    })
    .onUpdate((event) => {
      const x = event.x;
      const percentage = Math.max(
        -100,
        Math.min(100, ((x - sliderWidth / 2) / (sliderWidth / 2)) * 100)
      );
      onChange(percentage);
    })
    .onEnd(() => {
      console.log(`[Steering] Gesture ended`);
      onChange(0);
    })
    .onFinalize(() => {
      onChange(0);
    });

  return (
    <View style={styles.steeringContainer}>
      <Text style={styles.sliderLabel}>STEERING</Text>
      <GestureDetector gesture={panGesture}>
        <View
          ref={sliderRef}
          style={[styles.horizontalSlider, { width: sliderWidth }]}
          onLayout={(event) => {
            sliderRef.current?.measureInWindow((pageX, pageY) => {
              sliderBounds.current = { x: pageX, y: pageY, width: sliderWidth, height: 60 };
              console.log(`[Steering] Layout bounds:`, sliderBounds.current);
            });
          }}
        >
        <View style={styles.sliderCenter} />
        <View
          pointerEvents="none"
          style={[
            styles.sliderThumb,
            {
              left: sliderWidth / 2 + (value / 100) * (sliderWidth / 2) - 20,
            },
          ]}
        >
          <LinearGradient
            colors={["#f59e0b", "#d97706"]}
            style={styles.thumbGradient}
          />
        </View>
        </View>
      </GestureDetector>
      <View style={styles.sliderLabelsHorizontal}>
        <Text style={styles.sliderLabelText}>LEFT</Text>
        <Text style={styles.sliderLabelText}>RIGHT</Text>
      </View>
    </View>
  );
}

interface DraggableResizableCameraProps {
  piIP: string;
  position: { x: number; y: number };
  onPositionChange: (pos: { x: number; y: number }) => void;
  size: { width: number; height: number };
  onSizeChange: (size: { width: number; height: number }) => void;
  cameraError: boolean;
  onCameraError: (error: boolean) => void;
  cameraKey: number;
  onRefresh: () => void;
  isFullscreen: boolean;
  onFullscreenChange: (fullscreen: boolean) => void;
}

function DraggableResizableCamera({ 
  piIP, 
  position, 
  onPositionChange, 
  size, 
  onSizeChange,
  cameraError,
  onCameraError,
  cameraKey,
  onRefresh,
  isFullscreen,
  onFullscreenChange
}: DraggableResizableCameraProps) {
  const pan = useRef(new Animated.ValueXY(position)).current;
  const [isResizing, setIsResizing] = useState(false);
  const webViewRef = useRef<WebView>(null);
  
  const cleanIP = piIP.replace(/^(https?:\/\/)/i, '').replace(/^(wss?:\/\/)/i, '').replace(/\/+$/, '');
  
  const isNgrok = cleanIP.includes('.ngrok-free.dev') || cleanIP.includes('.ngrok-free.app') || cleanIP.includes('.ngrok.');
  
  let cameraUrl: string;
  if (isNgrok) {
    const host = cleanIP.replace(/:\d+$/, '');
    cameraUrl = `https://${host}/camera`;
  } else if (cleanIP.includes(':')) {
    cameraUrl = `http://${cleanIP}/camera`;
  } else {
    cameraUrl = `http://${cleanIP}:8765/camera`;
  }
  
  console.log(`📹 Camera URL: ${cameraUrl}`);
  
  useEffect(() => {
    onCameraError(false);
  }, [cameraKey, onCameraError]);

  const dragPanResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => !isResizing,
    onStartShouldSetPanResponderCapture: () => !isResizing,
    onMoveShouldSetPanResponder: () => !isResizing,
    onMoveShouldSetPanResponderCapture: () => !isResizing,
    onPanResponderTerminationRequest: () => false,
    onPanResponderGrant: () => {
      pan.setOffset({
        x: position.x,
        y: position.y,
      });
      pan.setValue({ x: 0, y: 0 });
    },
    onPanResponderMove: Animated.event(
      [null, { dx: pan.x, dy: pan.y }],
      { useNativeDriver: false }
    ),
    onPanResponderRelease: (_, gesture) => {
      pan.flattenOffset();
      const newX = Math.max(0, Math.min(width - size.width, position.x + gesture.dx));
      const newY = Math.max(0, Math.min(height - size.height, position.y + gesture.dy));
      onPositionChange({ x: newX, y: newY });
      pan.setValue({ x: newX, y: newY });
    },
  });

  const initialSize = useRef(size);
  
  const resizePanResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onStartShouldSetPanResponderCapture: () => true,
    onMoveShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponderCapture: () => true,
    onPanResponderTerminationRequest: () => false,
    onPanResponderGrant: () => {
      console.log('📏 Starting resize');
      setIsResizing(true);
      initialSize.current = size;
    },
    onPanResponderMove: (_, gesture) => {
      const newWidth = Math.max(150, Math.min(width - 40, initialSize.current.width + gesture.dx));
      const newHeight = Math.max(100, Math.min(height - 100, initialSize.current.height + gesture.dy));
      onSizeChange({ width: newWidth, height: newHeight });
    },
    onPanResponderRelease: () => {
      console.log('📏 Resize ended');
      setIsResizing(false);
    },
  });

  const handleFullscreen = () => {
    onFullscreenChange(!isFullscreen);
  };

  if (isFullscreen) {
    return (
      <View style={styles.fullscreenContainer}>
        <View style={styles.fullscreenCameraView}>
          {Platform.OS === 'web' ? (
            <Image
              key={cameraKey}
              source={{ uri: cameraUrl }}
              style={styles.cameraWebView}
              contentFit="contain"
              onLoad={() => {
                console.log('✅ Camera stream loaded');
                onCameraError(false);
              }}
              onError={() => {
                console.error('❌ Camera stream error');
                onCameraError(true);
              }}
            />
          ) : (
            <WebView
              key={cameraKey}
              ref={webViewRef}
              source={{ 
                uri: cameraUrl,
                headers: {
                  'ngrok-skip-browser-warning': 'true',
                }
              }}
              style={styles.cameraWebView}
              onLoad={() => {
                console.log('✅ Camera WebView loaded');
                onCameraError(false);
              }}
              onLoadEnd={() => {
                console.log('✅ Camera stream ready');
              }}
              onError={(syntheticEvent: any) => {
                const { nativeEvent } = syntheticEvent;
                console.error('❌ Camera WebView error:', nativeEvent);
              }}
              onHttpError={(syntheticEvent: any) => {
                const { nativeEvent } = syntheticEvent;
                console.error('❌ Camera HTTP error:', nativeEvent.statusCode, nativeEvent.url);
              }}
              javaScriptEnabled={true}
              domStorageEnabled={false}
              startInLoadingState={false}
              scrollEnabled={false}
              bounces={false}
              overScrollMode="never"
              showsHorizontalScrollIndicator={false}
              showsVerticalScrollIndicator={false}
              mediaPlaybackRequiresUserAction={false}
              allowsInlineMediaPlayback={true}
            />
          )}
        </View>
        <Pressable onPress={handleFullscreen} style={styles.exitFullscreenButton}>
          <Maximize2 size={24} color="#ffffff" />
        </Pressable>
      </View>
    );
  }

  return (
    <Animated.View
      style={[
        styles.draggableCamera,
        {
          left: pan.x,
          top: pan.y,
          position: 'absolute' as const,
        },
      ]}
    >
      <View style={styles.cameraContainer}>
        <View style={styles.cameraHeader}>
          <View style={styles.cameraHeaderLeft} {...dragPanResponder.panHandlers}>
            <Video size={18} color="#f59e0b" />
          </View>
          <View style={styles.cameraHeaderRight}>
            <Pressable 
              onPress={handleFullscreen} 
              style={styles.fullscreenButton}
              hitSlop={{ top: 15, bottom: 15, left: 15, right: 15 }}
            >
              <Maximize2 size={18} color="#1a1410" />
            </Pressable>
            <View 
              {...resizePanResponder.panHandlers} 
              style={styles.resizeHandle}
              hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
            >
              <View style={styles.resizeIcon} />
            </View>
          </View>
        </View>
        <View style={[styles.cameraView, { width: size.width, height: size.height }]}>
          {Platform.OS === 'web' ? (
            <Image
              key={cameraKey}
              source={{ uri: cameraUrl }}
              style={styles.cameraWebView}
              contentFit="cover"
              onLoad={() => {
                console.log('✅ Camera stream loaded');
                onCameraError(false);
              }}
              onError={() => {
                console.error('❌ Camera stream error');
                onCameraError(true);
              }}
            />
          ) : (
            <WebView
              key={cameraKey}
              ref={webViewRef}
              source={{ 
                uri: cameraUrl,
                headers: {
                  'ngrok-skip-browser-warning': 'true',
                }
              }}
              style={styles.cameraWebView}
              pointerEvents="none"
              onLoad={() => {
                console.log('✅ Camera WebView loaded');
                onCameraError(false);
              }}
              onLoadEnd={() => {
                console.log('✅ Camera stream ready');
              }}
              onError={(syntheticEvent: any) => {
                const { nativeEvent } = syntheticEvent;
                console.error('❌ Camera WebView error:', nativeEvent);
              }}
              onHttpError={(syntheticEvent: any) => {
                const { nativeEvent } = syntheticEvent;
                console.error('❌ Camera HTTP error:', nativeEvent.statusCode, nativeEvent.url);
              }}
              javaScriptEnabled={true}
              domStorageEnabled={false}
              startInLoadingState={false}
              scrollEnabled={false}
              bounces={false}
              overScrollMode="never"
              showsHorizontalScrollIndicator={false}
              showsVerticalScrollIndicator={false}
              mediaPlaybackRequiresUserAction={false}
              allowsInlineMediaPlayback={true}
              mixedContentMode="always"
            />
          )}
        </View>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  statusBar: {
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  statusBarContent: {
    gap: 8,
  },
  statusBarRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  connectionStatus: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(0,0,0,0.3)",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  statusText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "700" as const,
    letterSpacing: 1,
  },
  errorContainer: {
    backgroundColor: "rgba(239, 68, 68, 0.2)",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(239, 68, 68, 0.4)",
  },
  errorText: {
    color: "#fca5a5",
    fontSize: 11,
    fontWeight: "600" as const,
    marginBottom: 2,
  },
  errorHint: {
    color: "#dc2626",
    fontSize: 10,
    fontWeight: "500" as const,
    opacity: 0.8,
  },
  settingsButton: {
    padding: 8,
    backgroundColor: "rgba(245, 158, 11, 0.2)",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(245, 158, 11, 0.4)",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.8)",
    justifyContent: "center",
    alignItems: "center",
    padding: 20,
  },
  modalContent: {
    backgroundColor: "#2d1810",
    borderRadius: 16,
    padding: 24,
    width: "100%",
    maxWidth: 400,
    borderWidth: 2,
    borderColor: "#f59e0b",
  },
  modalTitle: {
    color: "#f59e0b",
    fontSize: 18,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
    marginBottom: 20,
    textAlign: "center" as const,
  },
  inputContainer: {
    marginBottom: 20,
  },
  inputLabel: {
    color: "#f59e0b",
    fontSize: 12,
    fontWeight: "600" as const,
    marginBottom: 8,
    letterSpacing: 1,
  },
  input: {
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    borderWidth: 1,
    borderColor: "#f59e0b",
    borderRadius: 8,
    padding: 12,
    color: "#ffffff",
    fontSize: 16,
  },
  helpContainer: {
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    padding: 12,
    borderRadius: 8,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: "rgba(245, 158, 11, 0.2)",
  },
  helpTitle: {
    color: "#f59e0b",
    fontSize: 11,
    fontWeight: "700" as const,
    marginBottom: 8,
    letterSpacing: 0.5,
  },
  helpText: {
    color: "#d97706",
    fontSize: 11,
    marginBottom: 4,
  },
  modalButtons: {
    flexDirection: "row",
    gap: 12,
  },
  modalButton: {
    flex: 1,
    padding: 14,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: "#f59e0b",
    alignItems: "center",
  },
  modalButtonPrimary: {
    backgroundColor: "#f59e0b",
  },
  modalButtonText: {
    color: "#f59e0b",
    fontSize: 12,
    fontWeight: "700" as const,
    letterSpacing: 1,
  },
  modalButtonTextPrimary: {
    color: "#1a1410",
  },
  topControls: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    marginBottom: 20,
  },
  gearSection: {
    gap: 12,
  },
  sectionLabel: {
    color: "#f59e0b",
    fontSize: 12,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
  },
  gearButtons: {
    flexDirection: "row",
    gap: 12,
  },
  gearButton: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderWidth: 2,
    borderColor: "#f59e0b",
    alignItems: "center",
    justifyContent: "center",
  },
  gearButtonActive: {
    backgroundColor: "#f59e0b",
  },
  gearButtonText: {
    color: "#f59e0b",
    fontSize: 20,
    fontWeight: "700" as const,
  },
  gearButtonTextActive: {
    color: "#1a1410",
  },
  toggleButtonsContainer: {
    gap: 12,
  },
  toggleButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 25,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderWidth: 2,
    borderColor: "#f59e0b",
  },
  toggleButtonActive: {
    backgroundColor: "#f59e0b",
  },
  toggleButtonText: {
    color: "#f59e0b",
    fontSize: 14,
    fontWeight: "700" as const,
    letterSpacing: 1,
  },
  toggleButtonTextActive: {
    color: "#1a1410",
  },
  honkButton: {
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 25,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderWidth: 2,
    borderColor: "#f59e0b",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
  },
  honkButtonActive: {
    backgroundColor: "#f59e0b",
  },
  honkButtonText: {
    color: "#f59e0b",
    fontSize: 16,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
  },
  honkButtonTextActive: {
    color: "#1a1410",
  },
  mainControls: {
    flex: 1,
    flexDirection: "row",
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
    justifyContent: "space-between",
    alignItems: "flex-end",
  },
  throttleContainer: {
    alignItems: "center",
    gap: 12,
  },
  rightControls: {
    alignItems: "flex-end",
    gap: 16,
  },
  brakeContainer: {
    alignItems: "center",
    gap: 12,
  },
  steeringContainer: {
    alignItems: "center",
    gap: 12,
  },
  sliderLabel: {
    color: "#f59e0b",
    fontSize: 12,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
  },
  verticalSlider: {
    width: 60,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderRadius: 30,
    borderWidth: 2,
    borderColor: "#f59e0b",
    position: "relative" as const,
  },
  horizontalSlider: {
    height: 60,
    backgroundColor: "rgba(245, 158, 11, 0.1)",
    borderRadius: 30,
    borderWidth: 2,
    borderColor: "#f59e0b",
    position: "relative" as const,
  },
  sliderCenter: {
    position: "absolute" as const,
    top: "50%",
    left: "50%",
    transform: [{ translateX: -1.5 }, { translateY: -1.5 }],
    width: 3,
    height: 3,
    backgroundColor: "#f59e0b",
    borderRadius: 1.5,
  },
  sliderThumb: {
    position: "absolute" as const,
    width: 40,
    height: 40,
    borderRadius: 20,
  },
  thumbGradient: {
    width: 40,
    height: 40,
    borderRadius: 20,
  },
  sliderLabels: {
    width: 60,
    flexDirection: "column",
    justifyContent: "space-between",
  },
  sliderLabelsHorizontal: {
    width: "100%",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  sliderLabelText: {
    color: "#d97706",
    fontSize: 10,
    fontWeight: "600" as const,
    letterSpacing: 1,
  },
  troubleshootingContainer: {
    marginTop: 6,
    gap: 2,
  },
  draggableCamera: {
    zIndex: 100,
    position: "absolute" as const,
  },
  cameraContainer: {
    gap: 8,
  },
  cameraHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 8,
    paddingVertical: 8,
    backgroundColor: "rgba(0, 0, 0, 0.8)",
    borderRadius: 8,
    marginBottom: 4,
  },
  cameraHeaderLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flex: 1,
  },
  cameraHeaderRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  cameraLabel: {
    color: "#f59e0b",
    fontSize: 12,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
  },
  fullscreenButton: {
    padding: 8,
    backgroundColor: "rgba(245, 158, 11, 0.9)",
    borderRadius: 6,
  },
  cameraView: {
    backgroundColor: "#000000",
    borderRadius: 16,
    borderWidth: 2,
    borderColor: "#f59e0b",
    overflow: "hidden",
    position: "relative" as const,
  },
  cameraWebView: {
    width: "100%",
    height: "100%",
    backgroundColor: "#000000",
  },
  cameraOverlay: {
    position: "absolute" as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: "flex-start",
    alignItems: "flex-end",
    padding: 8,
  },
  cameraStatus: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(239, 68, 68, 0.9)",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  recordingDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#ffffff",
  },
  recordingText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "700" as const,
    letterSpacing: 1,
  },
  resizeHandle: {
    padding: 12,
    backgroundColor: "rgba(245, 158, 11, 0.9)",
    borderRadius: 6,
  },
  resizeIcon: {
    width: 16,
    height: 16,
    borderRightWidth: 3,
    borderBottomWidth: 3,
    borderColor: "#1a1410",
  },
  cameraLoading: {
    position: "absolute" as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "rgba(0, 0, 0, 0.7)",
  },
  cameraLoadingText: {
    color: "#f59e0b",
    fontSize: 14,
    fontWeight: "600" as const,
  },
  cameraErrorView: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 20,
    backgroundColor: "rgba(0, 0, 0, 0.8)",
  },
  cameraErrorText: {
    color: "#ef4444",
    fontSize: 16,
    fontWeight: "700" as const,
    marginBottom: 12,
    textAlign: "center" as const,
  },
  cameraErrorHint: {
    color: "#fca5a5",
    fontSize: 11,
    marginBottom: 4,
    textAlign: "center" as const,
  },
  cameraRetryButton: {
    marginTop: 16,
    paddingHorizontal: 20,
    paddingVertical: 10,
    backgroundColor: "#f59e0b",
    borderRadius: 8,
  },
  cameraRetryText: {
    color: "#1a1410",
    fontSize: 14,
    fontWeight: "700" as const,
  },
  fullscreenContainer: {
    position: "absolute" as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "#000000",
    zIndex: 1000,
  },
  fullscreenCameraView: {
    flex: 1,
  },
  exitFullscreenButton: {
    position: "absolute" as const,
    top: 50,
    right: 20,
    padding: 12,
    backgroundColor: "rgba(0, 0, 0, 0.6)",
    borderRadius: 8,
    borderWidth: 2,
    borderColor: "#f59e0b",
  },
});
