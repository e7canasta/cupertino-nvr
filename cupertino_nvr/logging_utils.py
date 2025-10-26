"""
Structured Logging Utilities
=============================

Utilities for structured JSON logging compatible with log aggregation
systems like Elasticsearch, Loki, etc.

Based on Adeline's logging architecture using pythonjsonlogger.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Any, Dict, Optional
import uuid

# ============================================================================
# Trace Context (propagación de trace_id)
# ============================================================================

# ContextVar para thread-safe trace propagation
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def get_trace_id() -> Optional[str]:
    """
    Obtiene el trace_id actual del contexto.

    Returns:
        Trace ID actual o None si no hay contexto activo
    """
    return trace_id_var.get()


def generate_trace_id(prefix: str = "trace") -> str:
    """
    Genera un nuevo trace ID único.

    Args:
        prefix: Prefijo para el trace ID (ej: "cmd", "processor", "mqtt")

    Returns:
        Trace ID en formato: {prefix}-{short_uuid}
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@contextmanager
def trace_context(trace_id: Optional[str] = None):
    """
    Context manager para propagar trace_id en toda la call stack.

    Args:
        trace_id: ID de trace a propagar. Si None, genera uno automático.

    Usage:
        with trace_context(f"cmd-{uuid.uuid4().hex[:8]}"):
            # Todo lo que se ejecute aquí tiene acceso al trace_id
            process_command()
            logger.info("Action", extra={"trace_id": get_trace_id()})
    """
    if trace_id is None:
        trace_id = generate_trace_id()

    token = trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        trace_id_var.reset(token)


# ============================================================================
# Logger Setup
# ============================================================================

def setup_structured_logging(
    level: str = "INFO",
    json_format: bool = True,
    indent: Optional[int] = None,
    output_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """
    Setup structured logging (JSON) para la aplicación.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, use JSON format. If False, use human-readable format.
        indent: JSON indent para pretty-print (None = compact, 2 = readable)
        output_file: Path al archivo de logs (None = stdout). Si se especifica, usa rotation.
        max_bytes: Tamaño máximo por archivo antes de rotar (default 10 MB)
        backup_count: Número de archivos backup a mantener (default 5)

    Usage:
        # Desarrollo (stdout, pretty-print)
        setup_structured_logging(level="DEBUG", json_format=False)

        # Producción (JSON, file con rotation)
        setup_structured_logging(
            level="INFO",
            json_format=True,
            output_file="logs/nvr.log",
            max_bytes=10*1024*1024,
            backup_count=5
        )
    """
    if json_format:
        try:
            from pythonjsonlogger import jsonlogger
        except ImportError:
            raise ImportError(
                "pythonjsonlogger not found. Install with: pip install python-json-logger"
            )

        # Custom formatter que agrega campos globales y renombra
        class CustomJsonFormatter(jsonlogger.JsonFormatter):
            def add_fields(self, log_record, record, message_dict):
                super().add_fields(log_record, record, message_dict)

                # Renombrar campos para consistencia
                if 'levelname' in log_record:
                    log_record['level'] = log_record.pop('levelname')

                if 'name' in log_record:
                    log_record['logger'] = log_record.pop('name')

                # Agregar trace_id del contexto si existe
                current_trace_id = get_trace_id()
                if current_trace_id and 'trace_id' not in log_record:
                    log_record['trace_id'] = current_trace_id

        formatter = CustomJsonFormatter(
            '%(timestamp)s %(level)s %(logger)s %(message)s',
            timestamp=True,
            json_indent=indent
        )
    else:
        # Human-readable formatter para desarrollo
        class HumanReadableFormatter(logging.Formatter):
            def __init__(self):
                super().__init__(
                    fmt="%(asctime)s | %(levelname)-8s | %(component)-20s | %(event)-20s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S"
                )
            
            def format(self, record: logging.LogRecord) -> str:
                # Add defaults for missing fields
                if not hasattr(record, "component"):
                    record.component = record.name.split(".")[-1]
                if not hasattr(record, "event"):
                    record.event = "-"
                
                return super().format(record)
        
        formatter = HumanReadableFormatter()

    # Custom StreamHandler that auto-flushes after each log
    class AutoFlushStreamHandler(logging.StreamHandler):
        """StreamHandler that flushes after every emit."""
        def emit(self, record):
            super().emit(record)
            self.flush()

    # Configurar handler (stdout o file con rotation)
    if output_file:
        # File handler con rotation automático
        log_path = Path(output_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )

        # Log inicial para confirmar rotation setup
        print(f"📄 Logging to file: {output_file} (max: {max_bytes//1024//1024}MB, backups: {backup_count})", file=sys.stderr)
    else:
        # Stdout handler with auto-flush for real-time logging
        handler = AutoFlushStreamHandler(sys.stdout)

    handler.setFormatter(formatter)

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove default handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper()))



# ============================================================================
# Helper Functions (simplificados - solo facilitan el patrón extra={})
# ============================================================================

def log_event(
    logger: logging.Logger,
    level: str,
    message: str,
    component: str,
    event: str,
    **kwargs
) -> None:
    """
    Helper para logs estructurados con component/event.
    
    Args:
        logger: Logger instance
        level: Log level (info, warning, error, etc.)
        message: Human-readable message
        component: Component name
        event: Event type
        **kwargs: Additional structured fields
    
    Example:
        >>> logger = logging.getLogger(__name__)
        >>> log_event(logger, "info", "Command received", "control_plane", "command_received", command="pause")
    """
    extra = {
        "component": component,
        "event": event,
        **kwargs
    }
    
    log_method = getattr(logger, level.lower())
    log_method(message, extra=extra)


def log_command(
    logger: logging.Logger,
    command: str,
    status: str,
    component: str = "control_plane",
    **kwargs
) -> None:
    """Helper para logs de comandos MQTT."""
    log_event(
        logger,
        "info" if status in ["received", "completed"] else "error",
        f"Command {command} {status}",
        component=component,
        event=f"command_{status}",
        command=command,
        command_status=status,
        **kwargs
    )


def log_mqtt_event(
    logger: logging.Logger,
    event_type: str,
    topic: str,
    component: str = "mqtt",
    **kwargs
) -> None:
    """Helper para logs de eventos MQTT."""
    log_event(
        logger,
        "info",
        f"MQTT {event_type}: {topic}",
        component=component,
        event=f"mqtt_{event_type}",
        mqtt_topic=topic,
        **kwargs
    )


def log_error_with_context(
    logger: logging.Logger,
    message: str,
    component: str,
    event: str,
    error: Optional[Exception] = None,
    **kwargs
) -> None:
    """Helper para logs de errores con contexto completo."""
    extra = {
        "component": component,
        "event": event,
        **kwargs
    }
    
    if error:
        extra["error_type"] = type(error).__name__
        extra["error_message"] = str(error)
    
    logger.error(message, extra=extra, exc_info=error is not None)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Setup
    "setup_structured_logging",
    # Trace context
    "trace_context",
    "get_trace_id",
    "generate_trace_id",
    # Helpers
    "log_event",
    "log_command",
    "log_mqtt_event",
    "log_error_with_context",
]

