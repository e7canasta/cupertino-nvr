# Quick Win Fase 1: Template Method para add_stream/remove_stream

**Prioridad:** ALTA
**Esfuerzo:** 1-2 días
**Impacto:** Reduce command_handlers.py de 730 → ~620 líneas (-110 líneas, -15%)

---

## 🎯 Objetivo

Eliminar duplicación entre `handle_add_stream()` y `handle_remove_stream()` usando **Template Method Pattern** (igual que `_execute_config_change()`).

---

## 📋 Análisis del Problema

### Código Actual (DRY Violation)

`cupertino_nvr/processor/command_handlers.py`

**handle_add_stream (líneas 271-360):**
```python
def handle_add_stream(self, params: dict):
    source_id = params.get("source_id")
    if source_id is None:
        raise ValueError("Missing required parameter: source_id")

    # Validate source_id
    try:
        source_id = int(source_id)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid source_id value: {source_id}") from e

    logger.info("ADD_STREAM command executing", extra={...})

    # Publish intermediate status
    if self.control_plane:
        self.control_plane.publish_status("reconfiguring")

    # Backup for rollback
    old_stream_uris = list(self.config.stream_uris)
    old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

    # Set restart flag BEFORE calling restart (for join() detection)
    if self.processor:
        self.processor._is_restarting = True

    try:
        # Use config's add_stream method (validates + constructs URI)
        self.config.add_stream(source_id)
        stream_uri = self.config.stream_uris[-1]

        logger.info("Stream config updated, restarting pipeline", extra={...})

        # Restart pipeline with updated config
        self.pipeline.restart_pipeline()

        logger.info("ADD_STREAM completed successfully", extra={...})

    except (ConfigValidationError, Exception) as e:
        # Rollback to backup
        self.config.stream_uris = old_stream_uris
        self.config.source_id_mapping = old_source_id_mapping

        logger.error("ADD_STREAM failed, rolled back", extra={...}, exc_info=True)

        if self.control_plane:
            self.control_plane.publish_status("error")

        raise
    finally:
        # Clear restart flag
        if self.processor:
            self.processor._is_restarting = False
```

**handle_remove_stream (líneas 361-446):**
```python
def handle_remove_stream(self, params: dict):
    source_id = params.get("source_id")
    if source_id is None:
        raise ValueError("Missing required parameter: source_id")

    # Validate source_id
    try:
        source_id = int(source_id)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid source_id value: {source_id}") from e

    logger.info("REMOVE_STREAM command executing", extra={...})

    # Publish intermediate status
    if self.control_plane:
        self.control_plane.publish_status("reconfiguring")

    # Backup for rollback
    old_stream_uris = list(self.config.stream_uris)
    old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

    # Set restart flag BEFORE calling restart (for join() detection)
    if self.processor:
        self.processor._is_restarting = True

    try:
        # Use config's remove_stream method (validates + removes)
        self.config.remove_stream(source_id)

        logger.info("Stream config updated, restarting pipeline", extra={...})

        # Restart pipeline
        self.pipeline.restart_pipeline()

        logger.info("REMOVE_STREAM completed successfully", extra={...})

    except (ConfigValidationError, Exception) as e:
        # Rollback to backup
        self.config.stream_uris = old_stream_uris
        self.config.source_id_mapping = old_source_id_mapping

        logger.error("REMOVE_STREAM failed, rolled back", extra={...}, exc_info=True)

        if self.control_plane:
            self.control_plane.publish_status("error")

        raise
    finally:
        # Clear restart flag
        if self.processor:
            self.processor._is_restarting = False
```

### 🚨 Problemas Identificados

1. **170 líneas de código casi idéntico** (85 líneas cada handler)
2. **DRY violation**: Backup/rollback/restart logic duplicado
3. **Mantenimiento riesgoso**: Cambio en uno requiere cambio en el otro
4. **Validación duplicada**: `int(source_id)` en ambos lugares

---

## ✅ Solución: Template Method Pattern

### Filosofía del Manifiesto

> **"Patterns con Propósito"**
>
> Ya tenemos `_execute_config_change()` que hace exactamente esto para `change_model/set_fps`.
> Aplicar el mismo pattern a streams es consistente y elimina duplicación.

### Código Propuesto

#### Paso 1: Template Method (nuevo método privado)

```python
# cupertino_nvr/processor/command_handlers.py
# Agregar después de _execute_config_change() (línea ~709)

def _execute_stream_change(
    self,
    source_id: int,
    operation: Callable[[int], None],
    command_name: str
) -> None:
    """
    Template method for stream change commands (add/remove).

    Pattern: Validate → Backup → Execute → Rollback on error

    This eliminates duplication between handle_add_stream and handle_remove_stream.

    Args:
        source_id: Stream source ID to add or remove
        operation: Config method to call (config.add_stream or config.remove_stream)
        command_name: Command name for logging (e.g., "ADD_STREAM", "REMOVE_STREAM")

    Raises:
        ConfigValidationError: If validation or operation fails (after rollback)
    """
    logger.info(
        f"{command_name} executing",
        extra={
            "event": f"{command_name.lower()}_command_start",
            "source_id": source_id,
            "current_stream_count": len(self.config.stream_uris)
        }
    )

    # Publish intermediate status
    if self.control_plane:
        self.control_plane.publish_status("reconfiguring")

    # Backup for rollback (defensive copy)
    old_stream_uris = list(self.config.stream_uris)
    old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

    # Set restart flag BEFORE calling restart (for join() detection)
    if self.processor:
        self.processor._is_restarting = True

    try:
        # Execute operation (config.add_stream(source_id) or config.remove_stream(source_id))
        operation(source_id)

        logger.info(
            f"Stream config updated, restarting pipeline",
            extra={
                "event": f"{command_name.lower()}_config_updated",
                "new_stream_count": len(self.config.stream_uris)
            }
        )

        # Restart pipeline with updated config
        self.pipeline.restart_pipeline()

        logger.info(
            f"✅ {command_name} completed successfully",
            extra={
                "event": f"{command_name.lower()}_completed",
                "source_id": source_id,
                "new_stream_count": len(self.config.stream_uris)
            }
        )

    except (ConfigValidationError, Exception) as e:
        # Rollback to backup
        self.config.stream_uris = old_stream_uris
        self.config.source_id_mapping = old_source_id_mapping

        logger.error(
            f"❌ {command_name} failed, rolled back",
            extra={
                "event": f"{command_name.lower()}_failed",
                "error_type": type(e).__name__,
                "error_message": str(e)
            },
            exc_info=True
        )

        if self.control_plane:
            self.control_plane.publish_status("error")

        raise
    finally:
        # Clear restart flag
        if self.processor:
            self.processor._is_restarting = False
```

#### Paso 2: Refactorizar handle_add_stream

```python
def handle_add_stream(self, params: dict):
    """
    Handle ADD_STREAM command.

    Params:
        source_id (int): Source ID to add (e.g., 8)

    Stream URI is constructed automatically from stream_server config.
    """
    # Validate parameter presence
    source_id = params.get("source_id")
    if source_id is None:
        raise ValueError("Missing required parameter: source_id")

    # Validate source_id type
    try:
        source_id = int(source_id)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid source_id value: {source_id}") from e

    # Execute using template method
    return self._execute_stream_change(
        source_id=source_id,
        operation=self.config.add_stream,
        command_name="ADD_STREAM"
    )
```

#### Paso 3: Refactorizar handle_remove_stream

```python
def handle_remove_stream(self, params: dict):
    """
    Handle REMOVE_STREAM command.

    Params:
        source_id (int): Source ID to remove (e.g., 2)
    """
    # Validate parameter presence
    source_id = params.get("source_id")
    if source_id is None:
        raise ValueError("Missing required parameter: source_id")

    # Validate source_id type
    try:
        source_id = int(source_id)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid source_id value: {source_id}") from e

    # Execute using template method
    return self._execute_stream_change(
        source_id=source_id,
        operation=self.config.remove_stream,
        command_name="REMOVE_STREAM"
    )
```

---

## 📊 Impacto del Cambio

### Antes (líneas de código)
- `handle_add_stream`: 85 líneas (271-360)
- `handle_remove_stream`: 85 líneas (361-446)
- **Total**: 170 líneas

### Después (líneas de código)
- `_execute_stream_change` (template): ~75 líneas (nuevo)
- `handle_add_stream`: ~20 líneas (simplificado)
- `handle_remove_stream`: ~20 líneas (simplificado)
- **Total**: ~115 líneas

**Reducción**: -55 líneas (-32%)

### command_handlers.py Total
- Antes: 730 líneas
- Después: ~675 líneas
- **Reducción**: -55 líneas (-7.5%)

---

## 🔧 Plan de Implementación

### Paso 1: Preparación (5 min)
```bash
# Backup del archivo actual
cp cupertino_nvr/processor/command_handlers.py \
   cupertino_nvr/processor/command_handlers.py.backup_fase1

# Crear branch (opcional)
git checkout -b refactor/quick-win-fase1-template-method
```

### Paso 2: Implementación (30-45 min)

1. **Agregar `_execute_stream_change()` después de `_execute_config_change()`** (línea ~709)
   - Copiar código del template method propuesto
   - Verificar imports: `from typing import Callable`

2. **Refactorizar `handle_add_stream()`** (reemplazar líneas 271-360)
   - Mantener validación de parámetros (source_id presence + type)
   - Delegar a `_execute_stream_change()`

3. **Refactorizar `handle_remove_stream()`** (reemplazar líneas 361-446)
   - Mantener validación de parámetros (source_id presence + type)
   - Delegar a `_execute_stream_change()`

4. **Verificar compilación**
   ```bash
   python -m py_compile cupertino_nvr/processor/command_handlers.py
   ```

### Paso 3: Testing Manual (20-30 min)

**Setup:**
```bash
# Terminal 1: MQTT broker
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto

# Terminal 2: Monitor MQTT
mosquitto_sub -t "nvr/#" -v | jq

# Terminal 3: Processor
cupertino-nvr processor --n 6 --enable-control --model yolov8x-640
```

**Test Cases:**

```bash
# Test 1: ADD_STREAM success
mosquitto_pub -t nvr/control/commands -m '{
  "command": "add_stream",
  "params": {"source_id": 8},
  "target_instances": ["*"]
}'

# Expected:
# - ACK "received"
# - Status "reconfiguring"
# - Pipeline restart log
# - Status "running"
# - ACK "completed"
# - Stream count increased

# Test 2: ADD_STREAM duplicate (debe fallar)
mosquitto_pub -t nvr/control/commands -m '{
  "command": "add_stream",
  "params": {"source_id": 8},
  "target_instances": ["*"]
}'

# Expected:
# - ACK "error"
# - Status "error"
# - Rollback log

# Test 3: REMOVE_STREAM success
mosquitto_pub -t nvr/control/commands -m '{
  "command": "remove_stream",
  "params": {"source_id": 8},
  "target_instances": ["*"]
}'

# Expected:
# - ACK "received"
# - Status "reconfiguring"
# - Pipeline restart log
# - Status "running"
# - ACK "completed"
# - Stream count decreased

# Test 4: REMOVE_STREAM not found (debe fallar)
mosquitto_pub -t nvr/control/commands -m '{
  "command": "remove_stream",
  "params": {"source_id": 999},
  "target_instances": ["*"]
}'

# Expected:
# - ACK "error"
# - Status "error"
# - ConfigValidationError log
```

**Validación:**
- ✅ Comportamiento idéntico al código original
- ✅ Rollback funciona en caso de error
- ✅ Logs estructurados correctos
- ✅ Estado de config consistente después de rollback

### Paso 4: Review + Commit (10 min)

```bash
# Review de cambios
git diff cupertino_nvr/processor/command_handlers.py

# Verificar reducción de líneas
wc -l cupertino_nvr/processor/command_handlers.py
# Debe ser ~675 líneas (era 730)

# Commit
git add cupertino_nvr/processor/command_handlers.py
git commit -m "refactor: Template method for add_stream/remove_stream commands

Eliminates DRY violation in stream change handlers.

Changes:
- Added _execute_stream_change() template method
- Refactored handle_add_stream() to use template (85L → 20L)
- Refactored handle_remove_stream() to use template (85L → 20L)

Benefits:
- Reduced duplication: -55 lines (-32% in handlers)
- Consistent error handling (backup/rollback pattern)
- Easier maintenance (single source of truth for stream changes)

Testing: Manual MQTT commands (add_stream, remove_stream with success/error cases)

Co-Authored-By: Gaby <noreply@visiona.com>"
```

---

## 🎸 Lecciones del Blues Aplicadas

### "Complejidad por diseño, no por accidente"
- ✅ Eliminamos complejidad accidental (duplicación)
- ✅ Mantenemos complejidad esencial (validación + rollback necesarios)

### "Patterns con Propósito"
- ✅ Template Method ya existe en `_execute_config_change()`
- ✅ Aplicar mismo pattern a streams es consistente
- ✅ No inventamos, reutilizamos

### "Simple para leer, NO simple para escribir una vez"
- ✅ Template method requiere más diseño inicial
- ✅ Pero hace código más fácil de leer y mantener
- ✅ Cambios futuros en UNO solo lugar

---

## ✅ Checklist de Completitud

- [ ] `_execute_stream_change()` agregado después de `_execute_config_change()`
- [ ] `handle_add_stream()` refactorizado (validación + delegación)
- [ ] `handle_remove_stream()` refactorizado (validación + delegación)
- [ ] Compilación OK (`python -m py_compile`)
- [ ] Test 1: ADD_STREAM success ✅
- [ ] Test 2: ADD_STREAM duplicate error ✅
- [ ] Test 3: REMOVE_STREAM success ✅
- [ ] Test 4: REMOVE_STREAM not found error ✅
- [ ] Logs estructurados correctos
- [ ] Rollback funciona en errores
- [ ] Reducción de líneas verificada (~675 líneas)
- [ ] Git commit con mensaje descriptivo

---

## 🚀 Next Steps

Después de completar Fase 1:
- Review QUICK_WIN_FASE_2_RESTART_COORDINATION.md
- Continuar con centralización de restart logic

---

**Versión:** 1.0
**Autor:** Gaby (Visiona AI)
**Fecha:** 2025-10-26
