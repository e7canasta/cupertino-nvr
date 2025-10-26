# Consultoría de Diseño: Refactoring para Legibilidad y Mantenibilidad

**Fecha:** 2025-10-26
**Proyecto:** Cupertino NVR
**Enfoque:** Atacar complejidad con diseño, KISS = código mantenible y legible

---

## Filosofía de esta Consultoría

> **"Un diseño limpio NO es un diseño complejo"**
> **"Complejidad por diseño, no por accidente"**
> **"Simple para leer, NO simple para escribir una vez"**

Esta consultoría NO propone agregar funcionalidad nueva. Propone **refactorings** que:
- ✅ Reducen complejidad accidental (sin tocar complejidad esencial)
- ✅ Mejoran legibilidad y mantenibilidad
- ✅ Facilitan testing y evolución futura
- ✅ Mantienen el mismo comportamiento observable

---

## Resumen Ejecutivo

### Estado Actual
El código funciona correctamente y la arquitectura de alto nivel (Data/Control/Metrics planes) es sólida. Sin embargo:

- **processor.py** es un God Object (1524 líneas) con múltiples responsabilidades
- Command handlers tienen duplicación de lógica (patrón backup/execute/rollback)
- Acoplamiento directo a infraestructura (paho.mqtt, InferencePipeline)
- Falta cohesión: métodos relacionados dispersos en la misma clase gigante

### Impacto de Refactoring
- **Testing:** Más fácil testear componentes aislados
- **Legibilidad:** Clases pequeñas con responsabilidad clara
- **Mantenibilidad:** Cambios localizados, menor riesgo de regresiones
- **Evolución:** Fácil agregar nuevos comandos o fuentes de datos

---

## Prioridad 1: Descomponer StreamProcessor (God Object)

### Problema

**processor.py tiene 1524 líneas y hace demasiado:**

```python
class StreamProcessor:
    # Gestión de pipeline
    def start(self): ...
    def join(self): ...
    def terminate(self): ...

    # Control plane (11 command handlers)
    def _handle_pause(self): ...
    def _handle_resume(self): ...
    def _handle_stop(self): ...
    def _handle_restart(self): ...
    def _handle_change_model(self): ...
    def _handle_set_fps(self): ...
    def _handle_add_stream(self): ...
    def _handle_remove_stream(self): ...
    def _handle_metrics(self): ...
    def _handle_ping(self): ...
    def _handle_rename_instance(self): ...

    # Metrics reporting
    def _get_full_metrics_report(self): ...
    def _get_lightweight_metrics(self): ...
    def _publish_metrics(self): ...
    def _start_metrics_reporting_thread(self): ...

    # Signal handling
    def _signal_handler(self): ...

    # MQTT setup
    def _init_mqtt_client(self): ...
```

**Violaciones de diseño:**
- ❌ **SRP (Single Responsibility Principle):** StreamProcessor tiene 5+ motivos para cambiar
- ❌ **Cohesión:** Métodos relacionados con control plane mezclados con pipeline lifecycle
- ❌ **Testing:** Difícil testear command handlers sin crear un pipeline completo

### Solución: Extraer Command Handlers a Clase Separada

**Nuevo diseño propuesto:**

```
StreamProcessor (lifecycle management)
    ├── InferencePipelineManager (pipeline lifecycle)
    ├── CommandHandlers (control plane logic)
    ├── MetricsReporter (metrics collection & publishing)
    └── MQTTControlPlane (MQTT client wrapper)
```

**Refactoring paso a paso:**

#### Paso 1: Extraer CommandHandlers

```python
# cupertino_nvr/processor/command_handlers.py
"""
Command Handlers for StreamProcessor Control Plane
===================================================

Handles all MQTT control commands (pause/resume/stop/restart/dynamic config).
"""
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class PipelineController(Protocol):
    """Protocol for controlling pipeline lifecycle."""
    def pause_pipeline(self) -> None: ...
    def resume_pipeline(self) -> None: ...
    def terminate_pipeline(self) -> None: ...
    def restart_pipeline(self, new_config: dict) -> None: ...


class CommandHandlers:
    """
    Centralized command handlers for MQTT control plane.

    Separates command execution logic from StreamProcessor lifecycle.
    Each command handler is small, focused, and testable.

    Args:
        pipeline_controller: Interface to control the inference pipeline
        config: Reference to StreamProcessorConfig (for dynamic updates)
        control_plane: MQTT control plane for status publishing
    """

    def __init__(
        self,
        pipeline_controller: PipelineController,
        config: object,  # StreamProcessorConfig
        control_plane: object  # MQTTControlPlane
    ):
        self.pipeline = pipeline_controller
        self.config = config
        self.control_plane = control_plane

    def handle_pause(self):
        """Handle PAUSE command - immediate stop of processing."""
        logger.info("⏸️  Executing PAUSE command")

        try:
            self.pipeline.pause_pipeline()
            self.control_plane.publish_status("paused")
            logger.info("✅ PAUSE completed")
        except Exception as e:
            logger.error(f"❌ PAUSE failed: {e}", exc_info=True)
            raise

    def handle_resume(self):
        """Handle RESUME command - resume processing."""
        logger.info("▶️  Executing RESUME command")

        try:
            self.pipeline.resume_pipeline()
            self.control_plane.publish_status("running")
            logger.info("✅ RESUME completed")
        except Exception as e:
            logger.error(f"❌ RESUME failed: {e}", exc_info=True)
            raise

    def handle_stop(self):
        """Handle STOP command - terminate completely."""
        logger.info("⏹️  Executing STOP command")

        try:
            self.pipeline.terminate_pipeline()
            self.control_plane.publish_status("stopped")
            logger.info("✅ STOP completed")
        except Exception as e:
            logger.error(f"❌ STOP failed: {e}", exc_info=True)
            raise

    def handle_change_model(self, params: dict):
        """
        Handle CHANGE_MODEL command with automatic rollback on failure.

        Uses transaction pattern: backup → execute → commit/rollback
        """
        return self._execute_config_change(
            param_name="model_id",
            param_value=params.get("model_id"),
            validator=self._validate_model_id,
            config_attr="model_id",
            command_name="CHANGE_MODEL"
        )

    def handle_set_fps(self, params: dict):
        """Handle SET_FPS command with validation and rollback."""
        return self._execute_config_change(
            param_name="max_fps",
            param_value=params.get("max_fps"),
            validator=self._validate_fps,
            config_attr="max_fps",
            command_name="SET_FPS"
        )

    # ========================================================================
    # Private: Transaction Pattern for Config Changes
    # ========================================================================

    def _execute_config_change(
        self,
        param_name: str,
        param_value: any,
        validator: callable,
        config_attr: str,
        command_name: str
    ):
        """
        Template method for config change commands.

        Pattern: Validate → Backup → Publish status → Execute → Rollback on error

        This eliminates duplication across change_model/set_fps/add_stream/remove_stream.
        """
        # 1. Validate params
        if param_value is None:
            raise ValueError(f"Missing required parameter: {param_name}")

        validated_value = validator(param_value)

        # 2. Backup for rollback
        old_value = getattr(self.config, config_attr)

        logger.info(
            f"{command_name} executing",
            extra={
                "command": command_name.lower(),
                f"old_{config_attr}": old_value,
                f"new_{config_attr}": validated_value
            }
        )

        # 3. Publish intermediate status
        self.control_plane.publish_status("reconfiguring")

        try:
            # 4. Update config
            setattr(self.config, config_attr, validated_value)

            # 5. Restart pipeline with new config
            self.pipeline.restart_pipeline(new_config={config_attr: validated_value})

            logger.info(f"✅ {command_name} completed")

        except Exception as e:
            # 6. Rollback on failure
            setattr(self.config, config_attr, old_value)
            self.control_plane.publish_status("error")

            logger.error(
                f"❌ {command_name} failed, rolled back",
                extra={
                    "command": command_name.lower(),
                    f"rolled_back_to": old_value,
                    "error": str(e)
                },
                exc_info=True
            )
            raise

    # ========================================================================
    # Private: Validators
    # ========================================================================

    @staticmethod
    def _validate_model_id(model_id: str) -> str:
        """Validate model_id parameter."""
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError(f"Invalid model_id: {model_id}")
        return model_id.strip()

    @staticmethod
    def _validate_fps(fps: any) -> float:
        """Validate max_fps parameter."""
        try:
            fps_float = float(fps)
            if fps_float <= 0:
                raise ValueError("max_fps must be > 0")
            return fps_float
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid max_fps value: {fps}") from e
```

**Beneficios:**
- ✅ **SRP:** CommandHandlers solo maneja lógica de comandos
- ✅ **Testeable:** Puedes mockear PipelineController y testear handlers aisladamente
- ✅ **Reutilizable:** `_execute_config_change()` elimina duplicación (DRY)
- ✅ **Claro:** Cada handler es corto y fácil de entender

#### Paso 2: Extraer InferencePipelineManager

```python
# cupertino_nvr/processor/pipeline_manager.py
"""
Inference Pipeline Lifecycle Manager
=====================================

Manages InferencePipeline lifecycle: creation, start, pause, resume, restart, terminate.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class InferencePipelineManager:
    """
    Manages InferencePipeline lifecycle.

    Responsibilities:
    - Create pipeline from config
    - Start/stop pipeline
    - Pause/resume streaming
    - Restart pipeline (terminate + recreate + start)

    This class isolates all InferencePipeline-specific logic from StreamProcessor.
    """

    def __init__(self, config, mqtt_sink, watchdog=None):
        self.config = config
        self.mqtt_sink = mqtt_sink
        self.watchdog = watchdog
        self.pipeline: Optional[object] = None
        self.is_paused = False

    def create_pipeline(self):
        """Create InferencePipeline instance (but don't start yet)."""
        from inference import InferencePipeline

        logger.info(
            "Creating InferencePipeline",
            extra={
                "model_id": self.config.model_id,
                "stream_count": len(self.config.stream_uris),
                "max_fps": self.config.max_fps
            }
        )

        self.pipeline = InferencePipeline.init(
            video_reference=self.config.stream_uris,
            model_id=self.config.model_id,
            on_prediction=self.mqtt_sink,
            watchdog=self.watchdog,
            max_fps=self.config.max_fps,
        )

        logger.info("Pipeline created successfully")
        return self.pipeline

    def start_pipeline(self):
        """Start pipeline processing (blocks during stream connection)."""
        if not self.pipeline:
            raise RuntimeError("Pipeline not created. Call create_pipeline() first.")

        logger.info("Starting pipeline (may block connecting to streams)...")
        self.pipeline.start(use_main_thread=False)
        logger.info("✅ Pipeline started")

    def pause_pipeline(self):
        """Pause pipeline processing (two-level: sink + stream)."""
        if not self.pipeline or self.is_paused:
            logger.warning("Cannot pause: pipeline not running or already paused")
            return

        # Two-level pause: sink first (immediate), pipeline second (gradual)
        self.mqtt_sink.pause()
        self.pipeline.pause_stream()
        self.is_paused = True

        logger.info("Pipeline paused")

    def resume_pipeline(self):
        """Resume pipeline processing."""
        if not self.pipeline or not self.is_paused:
            logger.warning("Cannot resume: pipeline not paused")
            return

        # Resume order: pipeline first (buffer), sink second (publish)
        self.pipeline.resume_stream()
        self.mqtt_sink.resume()
        self.is_paused = False

        logger.info("Pipeline resumed")

    def restart_pipeline(self, new_config: dict = None):
        """
        Restart pipeline (terminate + recreate + start).

        Args:
            new_config: Optional dict of config updates to apply before restart
        """
        logger.info("Restarting pipeline")

        # Apply config updates if provided
        if new_config:
            for key, value in new_config.items():
                setattr(self.config, key, value)
                logger.debug(f"Config updated: {key}={value}")

        # Terminate old pipeline
        if self.pipeline:
            self.pipeline.terminate()
            self.pipeline = None

        # Recreate watchdog if enabled
        if self.config.enable_watchdog:
            from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog
            self.watchdog = BasePipelineWatchDog()

        # Recreate and start
        self.create_pipeline()
        self.start_pipeline()
        self.is_paused = False

        logger.info("✅ Pipeline restarted")

    def terminate_pipeline(self):
        """Terminate pipeline completely."""
        if self.pipeline:
            logger.info("Terminating pipeline")
            self.pipeline.terminate()
            self.pipeline = None
            logger.info("Pipeline terminated")
```

**Beneficios:**
- ✅ **Cohesión:** Todo lo relacionado con pipeline lifecycle está junto
- ✅ **Testeable:** Puedes testear pause/resume/restart aisladamente
- ✅ **Claro:** Cada método tiene un propósito único
- ✅ **Reutilizable:** Puede usarse en otros servicios (ej: Adeline)

#### Paso 3: Nuevo StreamProcessor (Orchestrator)

```python
# cupertino_nvr/processor/processor.py (refactored)
"""
Stream Processor - Main Orchestrator
=====================================

Coordinates: Pipeline, Control Plane, Metrics Reporting.
"""
import logging
import signal
from typing import Optional

from cupertino_nvr.processor.config import StreamProcessorConfig
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.control_plane import MQTTControlPlane
from cupertino_nvr.processor.pipeline_manager import InferencePipelineManager
from cupertino_nvr.processor.command_handlers import CommandHandlers
from cupertino_nvr.processor.metrics_reporter import MetricsReporter

logger = logging.getLogger(__name__)

# Global stop flag for signal handling
STOP = False


class StreamProcessor:
    """
    Main orchestrator for headless stream processing.

    Responsibilities (delegated):
    - Pipeline management → InferencePipelineManager
    - Command handling → CommandHandlers
    - Metrics reporting → MetricsReporter
    - Control plane → MQTTControlPlane

    This class is now a thin orchestrator (not a God Object).
    """

    def __init__(self, config: StreamProcessorConfig):
        self.config = config

        # Components (created in start())
        self.mqtt_client: Optional[object] = None
        self.mqtt_sink: Optional[MQTTDetectionSink] = None
        self.pipeline_manager: Optional[InferencePipelineManager] = None
        self.control_plane: Optional[MQTTControlPlane] = None
        self.command_handlers: Optional[CommandHandlers] = None
        self.metrics_reporter: Optional[MetricsReporter] = None

        # State
        self.is_running = False

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """
        Start processor with correct initialization order.

        Order (CRITICAL):
        1. MQTT client + Sink
        2. Pipeline manager (create pipeline, don't start)
        3. Control plane (must be ready BEFORE pipeline starts)
        4. Metrics reporter
        5. Start pipeline (blocks connecting to streams)
        """
        logger.info("Starting StreamProcessor", extra={
            "instance_id": self.config.instance_id,
            "stream_count": len(self.config.stream_uris)
        })

        # 1. MQTT + Sink
        self.mqtt_client = self._init_mqtt_client()
        self.mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            config=self.config,
            source_id_mapping=self.config.source_id_mapping,
        )

        # 2. Pipeline Manager
        self.pipeline_manager = InferencePipelineManager(
            config=self.config,
            mqtt_sink=self.mqtt_sink,
            watchdog=None  # Created by pipeline_manager if enabled
        )
        self.pipeline_manager.create_pipeline()
        logger.info("Pipeline created (not started yet)")

        # 3. Control Plane (BEFORE pipeline.start!)
        if self.config.enable_control_plane:
            self._setup_control_plane()

        # 4. Metrics Reporter
        if self.config.metrics_reporting_interval > 0:
            self.metrics_reporter = MetricsReporter(
                watchdog=self.pipeline_manager.watchdog,
                mqtt_client=self.mqtt_client,
                config=self.config
            )
            self.metrics_reporter.start()

        # 5. Start Pipeline (blocks here!)
        logger.info("▶️  Starting InferencePipeline...")
        self.pipeline_manager.start_pipeline()
        self.is_running = True
        logger.info("✅ StreamProcessor running")

    def join(self):
        """Wait for pipeline to finish."""
        if self.pipeline_manager and self.pipeline_manager.pipeline:
            self.pipeline_manager.pipeline.join()

        self._cleanup()

    def terminate(self):
        """Stop processor completely."""
        global STOP
        STOP = True

        if self.pipeline_manager:
            self.pipeline_manager.terminate_pipeline()

        self.is_running = False

    # ========================================================================
    # Private: Control Plane Setup
    # ========================================================================

    def _setup_control_plane(self):
        """Initialize control plane and register commands."""
        logger.info("🎛️  Initializing MQTT Control Plane")

        self.control_plane = MQTTControlPlane(
            broker_host=self.config.mqtt_host,
            broker_port=self.config.mqtt_port,
            command_topic=self.config.control_command_topic,
            status_topic=self.config.control_status_topic,
            instance_id=self.config.instance_id,
        )

        # Create command handlers (delegates all command logic)
        self.command_handlers = CommandHandlers(
            pipeline_controller=self.pipeline_manager,
            config=self.config,
            control_plane=self.control_plane
        )

        # Register commands
        registry = self.control_plane.command_registry
        registry.register('pause', self.command_handlers.handle_pause)
        registry.register('resume', self.command_handlers.handle_resume)
        registry.register('stop', self.command_handlers.handle_stop)
        registry.register('change_model', self.command_handlers.handle_change_model)
        registry.register('set_fps', self.command_handlers.handle_set_fps)
        # ... register other commands

        # Connect
        if self.control_plane.connect(timeout=10):
            logger.info("✅ CONTROL PLANE READY")
            self.control_plane.publish_status("starting")
        else:
            logger.warning("⚠️  Control Plane connection failed")
            self.control_plane = None

    def _init_mqtt_client(self):
        """Initialize MQTT client."""
        import paho.mqtt.client as mqtt

        client = mqtt.Client()
        if self.config.mqtt_username:
            client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password)

        client.connect(self.config.mqtt_host, self.config.mqtt_port)
        client.loop_start()

        logger.info("MQTT client connected")
        return client

    def _cleanup(self):
        """Cleanup on shutdown."""
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()

        if self.control_plane:
            self.control_plane.disconnect()

        if self.metrics_reporter:
            self.metrics_reporter.stop()

        logger.info("StreamProcessor stopped")

    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        logger.info(f"Signal {signum} received, shutting down...")
        self.terminate()
```

**Nuevo tamaño:** ~150 líneas (vs 1524 originales)

**Beneficios:**
- ✅ **Claridad:** StreamProcessor es ahora un orchestrator limpio
- ✅ **SRP:** Cada componente tiene una responsabilidad
- ✅ **Testeable:** Cada componente puede testearse aisladamente
- ✅ **Mantenible:** Cambios localizados en componentes específicos

---

## Prioridad 2: Eliminar Duplicación en Config Changes

### Problema

Los 4 handlers de dynamic config tienen **código casi idéntico**:

```python
# DUPLICADO en: change_model, set_fps, add_stream, remove_stream
def _handle_change_model(self, params: dict):
    new_value = params.get('param')
    if not new_value:
        raise ValueError("Missing param")

    old_value = self.config.attr

    self.control_plane.publish_status("reconfiguring")

    try:
        self.config.attr = new_value
        self._handle_restart()
    except Exception as e:
        self.config.attr = old_value
        self.control_plane.publish_status("error")
        raise
```

**Violación:** DRY (Don't Repeat Yourself)

### Solución: Template Method Pattern

Ya implementado en `CommandHandlers._execute_config_change()` (ver Prioridad 1).

**Elimina ~200 líneas de código duplicado** con un solo método template.

---

## Prioridad 3: Introducir Abstracciones (Dependency Inversion)

### Problema

**Acoplamiento directo a infraestructura:**

```python
# processor.py está acoplado a paho.mqtt.Client
import paho.mqtt.client as mqtt
self.mqtt_client = mqtt.Client()

# Dificulta testing: necesitas un broker MQTT real
```

**Violación:** Dependency Inversion Principle (DIP)

### Solución: Introducir Interfaces/Protocols

```python
# cupertino_nvr/interfaces.py
"""
Interfaces for dependency injection.
"""
from typing import Protocol, Any


class MessageBroker(Protocol):
    """Protocol for MQTT-like message broker."""

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> Any:
        """Publish message to topic."""
        ...

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe to topic."""
        ...

    def connect(self, host: str, port: int) -> None:
        """Connect to broker."""
        ...

    def disconnect(self) -> None:
        """Disconnect from broker."""
        ...


class InferencePipeline(Protocol):
    """Protocol for inference pipeline."""

    def start(self, use_main_thread: bool = True) -> None:
        """Start pipeline."""
        ...

    def terminate(self) -> None:
        """Terminate pipeline."""
        ...

    def pause_stream(self) -> None:
        """Pause stream processing."""
        ...

    def resume_stream(self) -> None:
        """Resume stream processing."""
        ...

    def join(self) -> None:
        """Wait for pipeline to finish."""
        ...
```

**Uso:**

```python
# cupertino_nvr/processor/mqtt_sink.py
from cupertino_nvr.interfaces import MessageBroker

class MQTTDetectionSink:
    def __init__(
        self,
        mqtt_client: MessageBroker,  # Protocol, not concrete class
        topic_prefix: str,
        config: object,
    ):
        self.client = mqtt_client
        ...
```

**Beneficios:**
- ✅ **Testing:** Puedes usar un FakeMessageBroker para tests
- ✅ **Flexibilidad:** Fácil cambiar de paho.mqtt a otro cliente
- ✅ **Claridad:** La interfaz documenta qué métodos se usan realmente

**Test ejemplo:**

```python
# tests/unit/test_mqtt_sink.py
class FakeMessageBroker:
    """Fake MQTT broker for testing."""
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return type('Result', (), {'rc': 0})()


def test_mqtt_sink_publishes_detection():
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(stream_uris=["rtsp://..."])
    sink = MQTTDetectionSink(broker, "nvr/detections", config)

    # Mock prediction and frame
    prediction = {"predictions": [{"class": "person", "confidence": 0.9, ...}]}
    frame = MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.45)

    # Execute
    sink(prediction, frame)

    # Assert
    assert len(broker.published) == 1
    topic, payload, _, _ = broker.published[0]
    assert topic == "nvr/detections/0"
    assert "person" in payload
```

**Sin protocolo:** Necesitas levantar mosquitto para test unitario.
**Con protocolo:** Test instantáneo sin dependencias externas.

---

## Prioridad 4: Mejorar Config con Comportamiento

### Problema

**StreamProcessorConfig es solo un data bag:**

```python
@dataclass
class StreamProcessorConfig:
    stream_uris: List[str]
    model_id: str = "yolov8x-640"
    # ... 20 campos más
```

No tiene:
- ❌ Validación de datos
- ❌ Construcción de URIs (lógica dispersa en cli.py y handlers)
- ❌ Comportamiento relacionado con configuración

### Solución: Rich Config Object

```python
# cupertino_nvr/processor/config.py (refactored)
"""
StreamProcessor Configuration with validation and behavior.
"""
from dataclasses import dataclass, field
from typing import List, Optional
import uuid
from urllib.parse import urlparse


class ConfigValidationError(ValueError):
    """Error en validación de configuración."""
    pass


@dataclass
class StreamProcessorConfig:
    """
    Configuration for headless stream processor.

    Now includes validation and URI construction behavior.
    """

    # Stream sources
    stream_uris: List[str]
    model_id: str = "yolov8x-640"

    # MQTT configuration
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "nvr/detections"

    # ... other fields

    stream_server: str = "rtsp://localhost:8554"
    instance_id: str = field(default_factory=lambda: f"processor-{uuid.uuid4().hex[:8]}")

    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate()

    def _validate(self):
        """Validate configuration values."""
        # Validate stream URIs
        if not self.stream_uris:
            raise ConfigValidationError("stream_uris cannot be empty")

        for uri in self.stream_uris:
            if not self._is_valid_uri(uri):
                raise ConfigValidationError(f"Invalid stream URI: {uri}")

        # Validate MQTT port
        if not (1 <= self.mqtt_port <= 65535):
            raise ConfigValidationError(f"Invalid MQTT port: {self.mqtt_port}")

        # Validate max_fps
        if self.max_fps is not None and self.max_fps <= 0:
            raise ConfigValidationError(f"max_fps must be > 0, got {self.max_fps}")

        # Validate metrics interval
        if self.metrics_reporting_interval < 0:
            raise ConfigValidationError("metrics_reporting_interval cannot be negative")

    @staticmethod
    def _is_valid_uri(uri: str) -> bool:
        """Check if URI is valid."""
        try:
            result = urlparse(uri)
            return all([result.scheme, result.netloc or result.path])
        except Exception:
            return False

    # ========================================================================
    # Behavior: URI Construction
    # ========================================================================

    def build_stream_uri(self, source_id: int) -> str:
        """
        Build stream URI from stream_server and source_id.

        go2rtc pattern: rtsp://server/{source_id}

        Args:
            source_id: Stream source ID (room number)

        Returns:
            Full RTSP URI

        Example:
            >>> config = StreamProcessorConfig(stream_server="rtsp://go2rtc:8554", ...)
            >>> config.build_stream_uri(8)
            'rtsp://go2rtc:8554/8'
        """
        return f"{self.stream_server}/{source_id}"

    def add_stream(self, source_id: int) -> None:
        """
        Add stream to configuration.

        Constructs URI and updates stream_uris and source_id_mapping.

        Args:
            source_id: Stream source ID to add

        Raises:
            ConfigValidationError: If source_id already exists
        """
        if source_id in self.source_id_mapping:
            raise ConfigValidationError(f"Stream {source_id} already exists")

        stream_uri = self.build_stream_uri(source_id)
        self.stream_uris.append(stream_uri)
        self.source_id_mapping.append(source_id)

    def remove_stream(self, source_id: int) -> None:
        """
        Remove stream from configuration.

        Args:
            source_id: Stream source ID to remove

        Raises:
            ConfigValidationError: If source_id not found
        """
        if source_id not in self.source_id_mapping:
            raise ConfigValidationError(f"Stream {source_id} not found")

        idx = self.source_id_mapping.index(source_id)
        self.stream_uris.pop(idx)
        self.source_id_mapping.pop(idx)

    # ========================================================================
    # Behavior: Serialization for Status Publishing
    # ========================================================================

    def to_status_dict(self) -> dict:
        """
        Serialize config for status publishing.

        Returns only relevant fields for orchestrator/monitoring.
        """
        return {
            "stream_uris": self.stream_uris,
            "source_id_mapping": self.source_id_mapping,
            "model_id": self.model_id,
            "max_fps": self.max_fps,
            "stream_server": self.stream_server,
            "mqtt_topic_prefix": self.mqtt_topic_prefix,
        }
```

**Beneficios:**
- ✅ **Validación:** Errores detectados en carga, no en runtime
- ✅ **Cohesión:** URI construction está donde debe estar (en config)
- ✅ **Reutilizable:** `add_stream/remove_stream` eliminan lógica de handlers
- ✅ **Testeable:** Puedes testear validación independientemente

**Simplifica command handlers:**

```python
# ANTES (en handler)
def _handle_add_stream(self, params: dict):
    source_id = int(params.get('source_id'))
    if source_id in self.config.source_id_mapping:
        raise ValueError("Already exists")

    stream_uri = f"{self.config.stream_server}/{source_id}"
    self.config.stream_uris.append(stream_uri)
    self.config.source_id_mapping.append(source_id)
    ...

# DESPUÉS (con rich config)
def handle_add_stream(self, params: dict):
    source_id = int(params.get('source_id'))
    self.config.add_stream(source_id)  # Validation + construction inside config
    self.pipeline.restart_pipeline()
```

---

## Prioridad 5: Simplificar Logging Helpers

### Problema

**Logging helpers son wrappers innecesarios:**

```python
# logging_utils.py
def log_event(logger, level, message, component, event, **kwargs):
    extra = {"component": component, "event": event, **kwargs}
    log_method = getattr(logger, level.lower())
    log_method(message, extra=extra)

def log_command(logger, command, status, component="control_plane", **kwargs):
    log_event(logger, "info" if ... else "error", ..., component, ...)

def log_mqtt_event(logger, event_type, topic, component="mqtt", **kwargs):
    log_event(logger, "info", ..., component, ...)
```

**Problema:**
- Agrega complejidad sin valor real
- El código directo sería más simple: `logger.info("message", extra={...})`

### Solución: Usar Logging Directo + LoggerAdapter

```python
# cupertino_nvr/logging_utils.py (simplified)
"""
Structured Logging Utilities
=============================

Simple utilities for structured JSON logging.
"""
import logging
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional
import uuid

# Trace context (keep this - útil)
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)

def get_trace_id() -> Optional[str]:
    return trace_id_var.get()

@contextmanager
def trace_context(trace_id: Optional[str] = None):
    if trace_id is None:
        trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    token = trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        trace_id_var.reset(token)


# LoggerAdapter con component automático
class ComponentLogger(logging.LoggerAdapter):
    """
    Logger adapter que agrega 'component' automáticamente.

    Usage:
        logger = ComponentLogger(logging.getLogger(__name__), {"component": "processor"})
        logger.info("Pipeline started", extra={"event": "pipeline_started", "model_id": "yolo"})
        # Output: {"message": "Pipeline started", "component": "processor", "event": "pipeline_started", ...}
    """
    def process(self, msg, kwargs):
        # Merge component + trace_id + user extra
        extra = kwargs.get('extra', {})
        extra.update(self.extra)  # Add component

        # Add trace_id if available
        trace_id = get_trace_id()
        if trace_id:
            extra['trace_id'] = trace_id

        kwargs['extra'] = extra
        return msg, kwargs


def get_component_logger(name: str, component: str) -> ComponentLogger:
    """
    Get logger with component automatically added.

    Args:
        name: Logger name (usually __name__)
        component: Component name

    Returns:
        ComponentLogger instance

    Example:
        >>> logger = get_component_logger(__name__, "processor")
        >>> logger.info("Event", extra={"event": "test"})
        # Automatically includes component="processor"
    """
    base_logger = logging.getLogger(name)
    return ComponentLogger(base_logger, {"component": component})


# Setup function (keep as is - útil)
def setup_structured_logging(
    level: str = "INFO",
    json_format: bool = True,
    output_file: Optional[str] = None,
) -> None:
    """Setup structured logging (keep implementation as is)."""
    # ... (implementation unchanged)
```

**Uso simplificado:**

```python
# ANTES (con helpers)
from cupertino_nvr.logging_utils import log_event, log_command

logger = logging.getLogger(__name__)
log_event(logger, "info", "Command received", "control_plane", "command_received", command="pause")
log_command(logger, "pause", "received", component="control_plane")

# DESPUÉS (logging directo con ComponentLogger)
from cupertino_nvr.logging_utils import get_component_logger

logger = get_component_logger(__name__, "control_plane")
logger.info("Command received", extra={"event": "command_received", "command": "pause"})
logger.info("Command pause received", extra={"event": "command_received", "command": "pause"})
```

**Beneficios:**
- ✅ **Simplicidad:** Menos indirecciones, código más directo
- ✅ **Familiar:** Usa API estándar de logging
- ✅ **Potente:** ComponentLogger agrega component automáticamente
- ✅ **Reduce complejidad:** Elimina 3 funciones helper innecesarias

---

## Prioridad 6: Extraer MetricsReporter

### Problema

**Metrics reporting mezclado en processor.py:**

```python
# En StreamProcessor
def _get_full_metrics_report(self): ...
def _get_lightweight_metrics(self): ...
def _publish_metrics(self, topic, payload, retained): ...
def _start_metrics_reporting_thread(self): ...
```

**Violación:** SRP (métricas es una responsabilidad separada)

### Solución: Extraer a Clase Separada

```python
# cupertino_nvr/processor/metrics_reporter.py
"""
Metrics Reporter
================

Handles metrics collection and periodic reporting to MQTT.
"""
import logging
import threading
import time
import json
from datetime import datetime
from typing import Optional

from cupertino_nvr.interfaces import MessageBroker

logger = logging.getLogger(__name__)


class MetricsReporter:
    """
    Periodic metrics reporter using InferencePipeline watchdog.

    Collects metrics from watchdog and publishes them periodically to MQTT.

    Args:
        watchdog: InferencePipeline watchdog instance
        mqtt_client: MQTT client for publishing
        config: StreamProcessorConfig
    """

    def __init__(
        self,
        watchdog: Optional[object],
        mqtt_client: MessageBroker,
        config: object  # StreamProcessorConfig
    ):
        self.watchdog = watchdog
        self.mqtt_client = mqtt_client
        self.config = config

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start periodic metrics reporting in background thread."""
        if self.config.metrics_reporting_interval <= 0:
            logger.info("Metrics reporting disabled (interval = 0)")
            return

        if not self.watchdog:
            logger.warning("Watchdog not available, cannot start metrics reporting")
            return

        self._thread = threading.Thread(
            target=self._reporting_loop,
            daemon=True,
            name="MetricsReporter"
        )
        self._thread.start()

        logger.info(
            f"📊 Metrics reporting started (interval: {self.config.metrics_reporting_interval}s)",
            extra={
                "component": "metrics_reporter",
                "event": "metrics_started",
                "interval": self.config.metrics_reporting_interval
            }
        )

    def stop(self):
        """Stop metrics reporting."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=5)
            logger.info("Metrics reporting stopped")

    def get_full_report(self) -> dict:
        """Get full detailed metrics report (for METRICS command)."""
        if not self.watchdog:
            return {}

        report = self.watchdog.get_report()

        return {
            "timestamp": datetime.now().isoformat(),
            "instance_id": self.config.instance_id,
            "inference_throughput": report.inference_throughput,
            "latency_reports": [
                {
                    "source_id": r.source_id,
                    "frame_decoding_latency_ms": round(r.frame_decoding_latency * 1000, 2) if r.frame_decoding_latency else None,
                    "inference_latency_ms": round(r.inference_latency * 1000, 2) if r.inference_latency else None,
                    "e2e_latency_ms": round(r.e2e_latency * 1000, 2) if r.e2e_latency else None,
                }
                for r in report.latency_reports
            ],
            "sources_metadata": [
                {
                    "source_id": m.source_id,
                    "fps": m.fps,
                    "resolution": f"{m.width}x{m.height}" if m.width and m.height else None,
                }
                for m in report.sources_metadata
            ],
        }

    # ========================================================================
    # Private
    # ========================================================================

    def _reporting_loop(self):
        """Background thread loop for periodic reporting."""
        while not self._stop_event.wait(timeout=self.config.metrics_reporting_interval):
            try:
                metrics = self._get_lightweight_metrics()

                # Only publish if valid data
                if metrics.get("inference_throughput", 0) > 0:
                    self._publish_metrics(metrics)

            except Exception as e:
                logger.error(f"Error in metrics reporting: {e}", exc_info=True)

    def _get_lightweight_metrics(self) -> dict:
        """Get lightweight metrics (for periodic reporting)."""
        if not self.watchdog:
            return {}

        report = self.watchdog.get_report()

        latencies = [r.e2e_latency for r in report.latency_reports if r.e2e_latency]
        avg_latency_ms = round(sum(latencies) / len(latencies) * 1000, 2) if latencies else None

        return {
            "timestamp": datetime.now().isoformat(),
            "instance_id": self.config.instance_id,
            "inference_throughput": round(report.inference_throughput, 2),
            "avg_latency_ms": avg_latency_ms,
        }

    def _publish_metrics(self, metrics: dict):
        """Publish metrics to MQTT."""
        topic = f"{self.config.metrics_topic}/{self.config.instance_id}"
        payload = json.dumps(metrics)

        self.mqtt_client.publish(topic, payload, qos=0, retain=True)

        logger.debug(
            "📊 Metrics published",
            extra={
                "component": "metrics_reporter",
                "event": "metrics_published",
                "throughput": metrics.get("inference_throughput")
            }
        )
```

**Beneficios:**
- ✅ **SRP:** MetricsReporter tiene una sola responsabilidad
- ✅ **Testeable:** Puedes testear reporting aisladamente
- ✅ **Reutilizable:** Puede usarse en otros servicios
- ✅ **Claro:** Thread lifecycle está encapsulado

---

## Roadmap de Implementación

### Fase 1: Refactorings de Bajo Riesgo (1-2 días)

**Semana 1:**
1. ✅ Extraer `MetricsReporter` (Prioridad 6)
2. ✅ Simplificar logging helpers (Prioridad 5)
3. ✅ Agregar comportamiento a `StreamProcessorConfig` (Prioridad 4)

**Riesgo:** Bajo - componentes aislados, fácil rollback

### Fase 2: Descomposición de StreamProcessor (2-3 días)

**Semana 2:**
1. ✅ Extraer `InferencePipelineManager` (Prioridad 1, Paso 2)
2. ✅ Extraer `CommandHandlers` (Prioridad 1, Paso 1)
3. ✅ Refactorizar `StreamProcessor` como orchestrator (Prioridad 1, Paso 3)

**Riesgo:** Medio - requiere refactoring grande, pero sin cambio de comportamiento

### Fase 3: Abstracciones (1 día)

**Semana 3:**
1. ✅ Introducir `MessageBroker` protocol (Prioridad 3)
2. ✅ Introducir `InferencePipeline` protocol
3. ✅ Actualizar tests para usar fakes

**Riesgo:** Bajo - solo agrega abstracciones, no cambia lógica

### Testing durante Refactoring

**Estrategia:**
1. Antes de cada cambio: tests manuales de comandos MQTT
2. Después de cada cambio: mismo test, debe pasar
3. No cambiar comportamiento observable

**Comandos para testing:**

```bash
# Test sequence (debe funcionar igual antes y después)
./test_restart_command.sh
./test_dynamic_config.sh
./test_metrics.sh

# Monitor para verificar comportamiento
mosquitto_sub -t "nvr/#" -v | jq
```

---

## Métricas de Éxito

### Antes del Refactoring
- 📏 `processor.py`: 1524 líneas
- 🧪 Test unitarios: Difícil (necesita MQTT broker)
- 🔧 Agregar comando: ~100 líneas + cambios en 3 lugares
- 📖 Complejidad ciclomática: Alta (métodos de 50+ líneas)

### Después del Refactoring
- 📏 `processor.py`: ~150 líneas (orchestrator)
- 📏 Componentes separados: 5 archivos de ~200 líneas c/u
- 🧪 Test unitarios: Fácil (fakes/mocks sin infraestructura)
- 🔧 Agregar comando: ~30 líneas en `CommandHandlers`
- 📖 Complejidad ciclomática: Baja (métodos de 5-20 líneas)

**Objetivo cuantitativo:**
- Reducir complejidad de `processor.py` en >80%
- Aumentar cobertura de tests unitarios de 0% a >70%
- Reducir tiempo de agregar comando de ~2h a ~30min

---

## Lecciones del Blues 🎸

### "Complejidad por diseño, no por accidente"

**Antes:**
- God Object con 1524 líneas (complejidad accidental)
- Lógica dispersa sin cohesión

**Después:**
- Componentes pequeños con responsabilidad clara (complejidad esencial controlada)
- Cada clase tiene una razón de ser

### "Un diseño limpio NO es un diseño complejo"

**Antes:**
- 11 handlers con código duplicado
- Difícil entender flujo de ejecución

**Después:**
- Template method elimina duplicación
- Flujo claro: Command → Handler → PipelineManager

### "Simple para leer, NO simple para escribir una vez"

**Antes:**
- Rápido escribir todo en una clase (simple de escribir)
- Difícil entender y mantener (complejo de leer)

**Después:**
- Requiere pensar en separación de concerns (esfuerzo inicial)
- Fácil entender cada componente aisladamente (simple de leer)

---

## Conclusión

Este refactoring NO agrega features. Agrega **mantenibilidad, legibilidad y estabilidad**.

**El código actual funciona.** Pero el código propuesto:
- Es más fácil de entender (componentes pequeños con propósito claro)
- Es más fácil de testear (abstracciones permiten fakes)
- Es más fácil de evolucionar (agregar comandos/features es localizado)

**"El diablo sabe por diablo, no por viejo"** - Implementamos control plane y encontramos los límites del diseño actual. Este refactoring aplica las lecciones aprendidas.

**Next step:** Empezar por Fase 1 (bajo riesgo) y validar que el approach funciona antes de Fase 2.

