"""
Structured Logging Utilities
=============================

Simplified structured JSON logging utilities.

Refactored per DESIGN_CONSULTANCY_REFACTORING.md (Prioridad 5):
- Keep: trace_context, setup_structured_logging (useful)
- Add: ComponentLogger (LoggerAdapter with automatic component field)
- Remove: log_event, log_command, log_mqtt_event (unnecessary wrappers)

Philosophy: Direct logger.info(msg, extra={...}) is simpler than indirect helpers.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional
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
# ComponentLogger (LoggerAdapter for automatic component field)
# ============================================================================

class ComponentLogger(logging.LoggerAdapter):
    """
    Logger adapter that automatically adds 'component' and 'trace_id' fields.

    Simplifies structured logging by eliminating the need for helper functions.
    Just use standard logger.info(msg, extra={...}) and component is added automatically.

    Args:
        logger: Base logger
        extra: Dict with 'component' field (required)

    Usage:
        >>> logger = ComponentLogger(logging.getLogger(__name__), {"component": "processor"})
        >>> logger.info("Pipeline started", extra={"event": "pipeline_started", "model_id": "yolo"})
        # Output: {"message": "Pipeline started", "component": "processor", "event": "pipeline_started", ...}

    Note:
        - Component field is merged from adapter's extra dict
        - Trace ID is automatically added from context if available
        - User-provided extra fields override adapter defaults
    """

    def process(self, msg, kwargs):
        """
        Process log record: merge component + trace_id + user extra.

        Order of precedence (highest to lowest):
        1. User-provided extra (in kwargs)
        2. Adapter extra (self.extra - contains component)
        3. Trace ID from context (if available)
        """
        # Start with adapter's extra (contains component)
        extra = dict(self.extra)

        # Add trace_id if available
        trace_id = get_trace_id()
        if trace_id:
            extra['trace_id'] = trace_id

        # Merge with user-provided extra (user overrides adapter)
        if 'extra' in kwargs:
            extra.update(kwargs['extra'])

        kwargs['extra'] = extra
        return msg, kwargs


def get_component_logger(name: str, component: str) -> ComponentLogger:
    """
    Get logger with component automatically added to all log records.

    Convenience factory for ComponentLogger.

    Args:
        name: Logger name (usually __name__)
        component: Component name (e.g., "processor", "control_plane", "mqtt_sink")

    Returns:
        ComponentLogger instance

    Usage:
        >>> logger = get_component_logger(__name__, "processor")
        >>> logger.info("Event", extra={"event": "test", "foo": "bar"})
        # Automatically includes component="processor"
    """
    base_logger = logging.getLogger(name)
    return ComponentLogger(base_logger, {"component": component})


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
    # ComponentLogger
    "ComponentLogger",
    "get_component_logger",
]

