# Quick Wins v2 - Master Plan

**Fecha:** 2025-10-26
**Proyecto:** Cupertino NVR
**Contexto:** Post-refactorización de DESIGN_CONSULTANCY_REFACTORING.md

---

## 🎸 Filosofía: "Tocar buen blues con este código"

> **"El diablo sabe por diablo, no por viejo"**
> **"Pragmatismo > Purismo"**
> **"Patterns con Propósito"**

Este sprint NO agrega funcionalidad nueva. Aplica **quick wins** identificados después de la primera refactorización:
- ✅ Reducir complejidad accidental (DRY violations)
- ✅ Mejorar cohesión (SRP violations)
- ✅ Centralizar responsabilidades dispersas

---

## 📊 Estado Post-Refactorización v1

### Métricas Actuales

```
processor.py:                  489 líneas (era 1524) ✅
command_handlers.py:           730 líneas (nuevo)
pipeline_manager.py:           322 líneas (nuevo)
control_plane.py:              481 líneas
config.py:                     258 líneas (con validación + behavior)
metrics_reporter.py:           233 líneas (nuevo)
logging_utils.py:              289 líneas (simplificado)
interfaces.py:                 231 líneas (protocols)
mqtt_sink.py:                  200 líneas (thread-safe)
```

**Resultado v1:** God Object eliminado, responsabilidades delegadas ✅

### Oportunidades Identificadas

**command_handlers.py (730 líneas) tiene:**
1. ❌ Duplicación: `handle_add_stream` y `handle_remove_stream` (170 líneas duplicadas)
2. ❌ SRP violation: Flag `_is_restarting` seteado en 4 lugares diferentes
3. ⚠️ Validators como métodos estáticos al final del archivo (scattered)

---

## 🎯 Quick Wins Propuestos

### Fase 1: Template Method para add_stream/remove_stream
**Prioridad:** ALTA
**Esfuerzo:** 1-2 días
**Impacto:** Reduce command_handlers.py de 730 → ~620 líneas

**Problema:** DRY violation en manejo de streams
**Solución:** Template method `_execute_stream_change()` (igual que `_execute_config_change`)

📄 **Documento:** `QUICK_WIN_FASE_1_TEMPLATE_METHOD.md`

---

### Fase 2: Centralizar Restart Coordination
**Prioridad:** ALTA
**Esfuerzo:** 1 día
**Impacto:** Mejora cohesión SRP

**Problema:** Flag `_is_restarting` seteado en 4 lugares (handlers dispersos)
**Solución:** Método `restart_with_coordination()` en `InferencePipelineManager`

📄 **Documento:** `QUICK_WIN_FASE_2_RESTART_COORDINATION.md`

---

### Fase 3: Extraer CommandValidators
**Prioridad:** MEDIA
**Esfuerzo:** 1 día
**Impacto:** Testability + extensibilidad

**Problema:** Validators scattered como métodos estáticos
**Solución:** Bounded context `validators.py` con `CommandValidators` class

📄 **Documento:** `QUICK_WIN_FASE_3_VALIDATORS.md`

---

## 📅 Roadmap de Implementación

### Semana 1: Quick Wins de Alto Impacto

**Día 1-2: Fase 1 (Template Method)**
- Implementar `_execute_stream_change()`
- Refactorizar `handle_add_stream` y `handle_remove_stream`
- Tests manuales: add_stream, remove_stream

**Día 3: Fase 2 (Restart Coordination)**
- Implementar `restart_with_coordination()` en pipeline_manager
- Refactorizar 4 handlers que setean el flag
- Tests manuales: restart, change_model, set_fps, add_stream

**Día 4: Fase 3 (Validators)**
- Crear `validators.py` con bounded context
- Migrar validators existentes
- Agregar `validate_source_id()`
- Tests manuales: validación de parámetros inválidos

---

## 🧪 Estrategia de Testing

**Filosofía:** Tests manuales (pair-programming style)

### Test Sequence (debe funcionar igual antes y después)

```bash
# Setup: MQTT broker
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto

# Monitor MQTT (ventana aparte)
mosquitto_sub -t "nvr/#" -v | jq

# Test básico
./test_dynamic_config.sh

# Test add_stream
mosquitto_pub -t nvr/control/commands -m '{"command": "add_stream", "params": {"source_id": 8}, "target_instances": ["*"]}'

# Test remove_stream
mosquitto_pub -t nvr/control/commands -m '{"command": "remove_stream", "params": {"source_id": 2}, "target_instances": ["*"]}'

# Test change_model
mosquitto_pub -t nvr/control/commands -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}, "target_instances": ["*"]}'

# Test restart
mosquitto_pub -t nvr/control/commands -m '{"command": "restart", "target_instances": ["*"]}'
```

**Expectativa:** Todos los comandos deben funcionar igual que antes del refactor.

---

## 📈 Métricas de Éxito

### Pre-Quick Wins v2
- `command_handlers.py`: 730 líneas
- Duplicación: 170 líneas (add/remove stream)
- Restart coordination: 4 lugares dispersos
- Validators: Scattered en command_handlers

### Post-Quick Wins v2 (Objetivo)
- `command_handlers.py`: ~550 líneas (-180 líneas, -25%)
- Duplicación: Eliminada con template method
- Restart coordination: 1 solo lugar (pipeline_manager)
- Validators: Bounded context separado (~80 líneas)

**Score actual:** 9.0/10 (post v1)
**Score objetivo:** 9.3/10 (post v2)

---

## 🔮 Future Improvements (Lower Priority)

### Quick Win #4: Status Management Value Object
**Esfuerzo:** 2-3 días
**Impacto:** Claridad + estado explícito

- Value Object `ProcessorState` (immutable)
- Factory `ProcessorState.from_processor()`
- Estado separado de publicación MQTT

**Decisión:** SKIP por ahora (el código funciona, este es más conceptual que práctico)

---

### Quick Win #5: MQTT Client Factory (DI)
**Esfuerzo:** 1 día
**Impacto:** Testing sin broker real

- Constructor injection en `StreamProcessor`
- Factory method `_default_mqtt_factory()`
- `interfaces.py` ya tiene `MessageBroker` protocol ✅

**Decisión:** SKIP por ahora (tests manuales funcionan bien)

---

## 🎸 Lecciones del Blues Aplicadas

### "Complejidad por diseño, no por accidente"
- Fase 1: Elimina complejidad accidental (170 líneas duplicadas)
- Fase 2: Mejora diseño (restart coordination en el lugar correcto)

### "Patterns con Propósito"
- Template Method ya está en `_execute_config_change` → aplicarlo a streams también
- No inventamos patterns nuevos, reutilizamos los que ya funcionan

### "Pragmatismo > Purismo"
- Fases 1-3 son alto impacto/bajo esfuerzo
- Fases 4-5 son "nice to have" pero no críticas → SKIP

### "Cohesión > Ubicación"
- Restart coordination pertenece a pipeline lifecycle (InferencePipelineManager)
- Validators pertenecen a bounded context de validación (separado de ejecución)

---

## 📖 Documentos del Sprint

1. **QUICK_WIN_FASE_1_TEMPLATE_METHOD.md** - Template method para streams
2. **QUICK_WIN_FASE_2_RESTART_COORDINATION.md** - Centralizar restart logic
3. **QUICK_WIN_FASE_3_VALIDATORS.md** - Bounded context para validators

---

**Versión:** 2.0
**Autores:** Ernesto (Visiona) + Gaby (AI Companion)
**Contexto:** Post-refactorización DESIGN_CONSULTANCY_REFACTORING.md

---

**Next Steps:**
1. Review QUICK_WIN_FASE_1_TEMPLATE_METHOD.md
2. Implementar Fase 1 (1-2 días)
3. Tests manuales + pair review
4. Continuar con Fase 2

¡Buen blues, compañero! 🎸
