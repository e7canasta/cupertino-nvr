"""
MQTT Control Plane for StreamProcessor
=======================================

Lightweight control plane for headless stream processor.
Based on Adeline's control architecture but simplified.
"""
import json
import logging
from datetime import datetime
from threading import Event
from typing import Optional, Callable, Dict

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class CommandNotAvailableError(Exception):
    """Comando no está disponible."""
    pass


class CommandRegistry:
    """
    Registry de comandos MQTT disponibles.
    
    Usage:
        registry = CommandRegistry()
        registry.register('pause', processor.pause, "Pause processing")
        registry.execute('pause')
    """
    
    def __init__(self):
        self._commands: Dict[str, Callable] = {}
        self._descriptions: Dict[str, str] = {}
    
    def register(self, command: str, handler: Callable, description: str = ""):
        """Registra un comando"""
        if command in self._commands:
            logger.warning(f"Command '{command}' already registered, overwriting")
        
        self._commands[command] = handler
        self._descriptions[command] = description
        logger.debug(f"Command registered: {command} - {description}")
    
    def execute(self, command: str):
        """Ejecuta un comando"""
        if command not in self._commands:
            available = ', '.join(sorted(self._commands.keys()))
            raise CommandNotAvailableError(
                f"Command '{command}' not available. Available: {available}"
            )
        
        handler = self._commands[command]
        logger.debug(f"Executing command: {command}")
        return handler()
    
    def is_available(self, command: str) -> bool:
        """Verifica si comando está disponible"""
        return command in self._commands
    
    @property
    def available_commands(self):
        """Set de comandos disponibles"""
        return set(self._commands.keys())
    
    def get_help(self) -> Dict[str, str]:
        """Retorna dict de comandos con descripciones"""
        return dict(self._descriptions)


class MQTTControlPlane:
    """
    Control Plane para StreamProcessor vía MQTT.
    
    Comandos básicos:
    - pause: Pausa el procesamiento
    - resume: Reanuda el procesamiento
    - stop: Detiene completamente
    - status: Consulta estado actual
    
    Args:
        broker_host: MQTT broker hostname
        broker_port: MQTT broker port
        command_topic: Topic para recibir comandos
        status_topic: Topic para publicar estado
        client_id: MQTT client ID
        username: MQTT username (opcional)
        password: MQTT password (opcional)
    """
    
    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        command_topic: str = "nvr/control/commands",
        status_topic: str = "nvr/control/status",
        client_id: str = "nvr_control",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.command_topic = command_topic
        self.status_topic = status_topic
        self.client_id = client_id
        
        # Command registry
        self.command_registry = CommandRegistry()
        
        # MQTT Client
        self.client = mqtt.Client(client_id=client_id)
        if username and password:
            self.client.username_pw_set(username, password)
        
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        self._connected = Event()
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback cuando se conecta al broker"""
        if rc == 0:
            logger.info(
                f"Control Plane connected to broker at "
                f"{self.broker_host}:{self.broker_port}"
            )
            self.client.subscribe(self.command_topic, qos=1)
            logger.info(f"Subscribed to command topic: {self.command_topic}")
            self._connected.set()
            self.publish_status("connected")
        else:
            logger.error(
                f"Failed to connect to MQTT broker: {self.broker_host}:{self.broker_port} "
                f"(return code: {rc})"
            )
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback cuando se desconecta del broker"""
        logger.warning(f"Control Plane disconnected from broker (rc: {rc})")
        self._connected.clear()
    
    def _on_message(self, client, userdata, msg):
        """Callback cuando recibe un mensaje MQTT"""
        try:
            payload = msg.payload.decode('utf-8')
            command_data = json.loads(payload)
            command = command_data.get('command', '').lower()
            
            logger.info(f"📥 Received command: {command}")
            
            # Ejecutar comando vía registry
            try:
                self.command_registry.execute(command)
                logger.info(f"✅ Command '{command}' executed successfully")
            
            except CommandNotAvailableError as e:
                logger.warning(f"⚠️  {e}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decoding JSON: {msg.payload}")
        except Exception as e:
            logger.error(f"❌ Error processing MQTT message: {e}", exc_info=True)
    
    def publish_status(self, status: str):
        """
        Publica el estado actual.
        
        Args:
            status: Estado a publicar (ej: "paused", "running", "stopped")
        """
        message = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "client_id": self.client_id
        }
        self.client.publish(
            self.status_topic,
            json.dumps(message),
            qos=1,
            retain=True
        )
        logger.debug(f"Status published: {status}")
    
    def connect(self, timeout: float = 5.0) -> bool:
        """Conecta al broker MQTT"""
        try:
            logger.info(
                f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}"
            )
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            return self._connected.wait(timeout=timeout)
        except Exception as e:
            logger.error(
                f"Failed to connect to MQTT broker: {e}",
                exc_info=True
            )
            return False
    
    def disconnect(self):
        """Desconecta del broker MQTT"""
        logger.info("Disconnecting Control Plane...")
        self.publish_status("disconnected")
        self.client.loop_stop()
        self.client.disconnect()

