"""
MQTT Control Plane for StreamProcessor
=======================================

Lightweight control plane for headless stream processor.
Based on Adeline's control architecture but simplified.

Uses structured JSON logging for observability and log aggregation.
"""
import json
import logging
from datetime import datetime
from threading import Event
from typing import Optional, Callable, Dict

import paho.mqtt.client as mqtt

from cupertino_nvr.logging_utils import log_event, log_command, log_mqtt_event, log_error_with_context

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
    
    def execute(self, command: str, params: dict = None):
        """
        Ejecuta un comando.

        Args:
            command: Nombre del comando
            params: Parámetros del comando (opcional)
        """
        if command not in self._commands:
            available = ', '.join(sorted(self._commands.keys()))
            raise CommandNotAvailableError(
                f"Command '{command}' not available. Available: {available}"
            )

        handler = self._commands[command]
        logger.debug(f"Executing command: {command}")

        # Check if handler accepts params (signature inspection)
        import inspect
        sig = inspect.signature(handler)

        if params and len(sig.parameters) > 0:
            # Handler accepts params
            return handler(params)
        else:
            # Handler doesn't accept params (backward compatibility)
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
        instance_id: str = "processor-default",
        client_id: str = "nvr_control",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.command_topic = command_topic
        self.status_topic_prefix = status_topic  # Store as prefix for instance-specific topics
        self.instance_id = instance_id
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
            log_event(
                logger, "info",
                "Control Plane connected to MQTT broker",
                component="control_plane",
                event="broker_connected",
                broker_host=self.broker_host,
                broker_port=self.broker_port,
                return_code=rc
            )
            
            self.client.subscribe(self.command_topic, qos=1)
            
            log_mqtt_event(
                logger,
                "subscribed",
                self.command_topic,
                component="control_plane",
                qos=1
            )
            
            self._connected.set()
            self.publish_status("connected")
        else:
            log_error_with_context(
                logger,
                "Failed to connect to MQTT broker",
                component="control_plane",
                event="broker_connection_failed",
                broker_host=self.broker_host,
                broker_port=self.broker_port,
                return_code=rc
            )
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback cuando se desconecta del broker"""
        log_event(
            logger, "warning",
            "Control Plane disconnected from MQTT broker",
            component="control_plane",
            event="broker_disconnected",
            return_code=rc
        )
        self._connected.clear()
    
    def _on_message(self, client, userdata, msg):
        """Callback cuando recibe un mensaje MQTT"""
        try:
            payload = msg.payload.decode('utf-8')
            command_data = json.loads(payload)
            command = command_data.get('command', '').lower()
            params = command_data.get('params', {})  # Extract params
            target_instances = command_data.get('target_instances', ['*'])  # Default: broadcast

            # Filter: check if this instance should process the command
            if not self._should_process_command(target_instances):
                log_event(
                    logger, "debug",
                    "Command filtered (not targeted to this instance)",
                    component="control_plane",
                    event="command_filtered",
                    command=command,
                    target_instances=target_instances,
                    this_instance=self.instance_id
                )
                return

            # Log cuando recibe el comando
            log_mqtt_event(
                logger,
                "received",
                msg.topic,
                component="control_plane",
                command=command,
                params=params if params else None,
                target_instances=target_instances,
                this_instance=self.instance_id,
                payload=payload
            )

            # ACK inmediato (estándar IoT)
            log_command(logger, command, "received", component="control_plane")
            self._publish_ack(command, "received")

            # Ejecutar comando vía registry (con params)
            try:
                log_command(logger, command, "executing", component="control_plane")
                self.command_registry.execute(command, params)

                # ACK de completado
                self._publish_ack(command, "completed")
                log_command(logger, command, "completed", component="control_plane")

            except CommandNotAvailableError as e:
                log_error_with_context(
                    logger,
                    f"Command not available: {command}",
                    component="control_plane",
                    event="command_not_available",
                    command=command,
                    available_commands=sorted(self.command_registry.available_commands)
                )
                self._publish_ack(command, "error", str(e))
            except ValueError as e:
                # Parameter validation error
                log_error_with_context(
                    logger,
                    f"Invalid parameters for command: {command}",
                    component="control_plane",
                    event="command_invalid_params",
                    command=command,
                    error=e,
                    params=params
                )
                self._publish_ack(command, "error", str(e))

        except json.JSONDecodeError as e:
            log_error_with_context(
                logger,
                "Failed to decode MQTT JSON payload",
                component="control_plane",
                event="json_decode_error",
                error=e,
                raw_payload=str(msg.payload)
            )
        except Exception as e:
            log_error_with_context(
                logger,
                "Error processing MQTT message",
                component="control_plane",
                event="message_processing_error",
                error=e,
                mqtt_topic=msg.topic
            )
    
    def _should_process_command(self, target_instances) -> bool:
        """
        Check if this instance should process the command.
        
        Args:
            target_instances: List of instance IDs or ["*"] for broadcast
        
        Returns:
            True if command should be processed, False otherwise
        """
        # Broadcast: process if target_instances is ["*"], None, or empty
        if not target_instances or target_instances == ['*']:
            return True
        
        # Targeted: process if this instance_id is in the list
        return self.instance_id in target_instances
    
    def _publish_ack(self, command: str, ack_status: str, message: str = ""):
        """
        Publica ACK de comando (estándar IoT).
        
        Args:
            command: Comando que se está confirmando
            ack_status: Estado del ACK (received, completed, error)
            message: Mensaje adicional (opcional)
        """
        ack_topic = f"{self.status_topic_prefix}/{self.instance_id}/ack"
        payload = {
            "instance_id": self.instance_id,
            "command": command,
            "ack_status": ack_status,
            "timestamp": datetime.now().isoformat(),
            "client_id": self.client_id,
        }
        if message:
            payload["message"] = message
        
        self.client.publish(
            ack_topic,
            json.dumps(payload),
            qos=1,
            retain=False  # ACKs no se retienen
        )
        
        log_mqtt_event(
            logger,
            "published",
            ack_topic,
            component="control_plane",
            command=command,
            ack_status=ack_status,
            ack_message=message if message else None
        )
    
    def publish_status(self, status: str, **extra_fields):
        """
        Publica el estado actual a topic específico de esta instancia.
        
        Args:
            status: Estado a publicar (ej: "paused", "running", "stopped")
            **extra_fields: Campos adicionales para incluir en payload (config, health, etc)
        """
        # Topic incluye instance_id: nvr/control/status/{instance_id}
        topic = f"{self.status_topic_prefix}/{self.instance_id}"
        
        payload = {
            "instance_id": self.instance_id,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "client_id": self.client_id,
            **extra_fields  # Config, health, uptime, etc.
        }
        
        self.client.publish(
            topic,
            json.dumps(payload),
            qos=1,
            retain=True
        )
        
        log_mqtt_event(
            logger,
            "published",
            topic,
            component="control_plane",
            instance_id=self.instance_id,
            status=status,
            retained=True
        )
    
    def connect(self, timeout: float = 5.0) -> bool:
        """Conecta al broker MQTT"""
        try:
            log_event(
                logger, "info",
                "Connecting to MQTT broker",
                component="control_plane",
                event="broker_connection_attempt",
                broker_host=self.broker_host,
                broker_port=self.broker_port,
                timeout=timeout
            )
            
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            return self._connected.wait(timeout=timeout)
            
        except Exception as e:
            log_error_with_context(
                logger,
                "Failed to connect to MQTT broker",
                component="control_plane",
                event="broker_connection_exception",
                error=e,
                broker_host=self.broker_host,
                broker_port=self.broker_port
            )
            return False
    
    def disconnect(self):
        """Desconecta del broker MQTT"""
        log_event(
            logger, "info",
            "Disconnecting Control Plane",
            component="control_plane",
            event="control_plane_disconnect"
        )
        
        self.publish_status("disconnected")
        self.client.loop_stop()
        self.client.disconnect()

