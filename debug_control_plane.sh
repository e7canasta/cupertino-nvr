#!/bin/bash
#
# Script de diagnóstico para el Control Plane
#

echo "======================================================================="
echo "🔍 DIAGNÓSTICO DE CONTROL PLANE"
echo "======================================================================="
echo ""

# Check if processor is running
echo "1. Verificando si el processor está corriendo..."
if pgrep -f "cupertino-nvr processor" > /dev/null; then
    echo "   ✅ Processor está corriendo (PID: $(pgrep -f 'cupertino-nvr processor' | head -1))"
else
    echo "   ❌ Processor NO está corriendo"
    exit 1
fi
echo ""

# Check if broker is running
echo "2. Verificando MQTT broker..."
if nc -z localhost 1883 2>/dev/null; then
    echo "   ✅ MQTT broker está activo en localhost:1883"
else
    echo "   ❌ MQTT broker NO está activo"
    exit 1
fi
echo ""

# Check MQTT clients
echo "3. Verificando clientes MQTT conectados..."
mosquitto_sub -h localhost -t '$SYS/broker/clients/total' -C 1 -W 1 2>/dev/null
echo ""

# Test command publishing
echo "4. Testeando publicación de comando STATUS..."
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "status"}' -d 2>&1 | head -5
echo ""

# Monitor ACKs (timeout 3 seconds)
echo "5. Monitoreando ACKs (timeout 3s)..."
timeout 3 mosquitto_sub -h localhost -t "nvr/control/#" -v 2>/dev/null || echo "   ⚠️  No se recibieron ACKs en 3 segundos"
echo ""

# Monitor detections briefly
echo "6. Monitoreando detecciones (timeout 3s)..."
echo "   (Si hay detecciones, el pipeline está funcionando)"
timeout 3 mosquitto_sub -h localhost -t "nvr/detections/+" -v 2>/dev/null | head -3 || echo "   ⚠️  No se recibieron detecciones"
echo ""

echo "======================================================================="
echo "7. Test completo: PAUSE -> Verificar detenciones -> RESUME"
echo "======================================================================="
echo ""

echo "   a) Enviando comando PAUSE..."
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
sleep 1

echo "   b) Verificando detecciones (deberían detenerse, timeout 5s)..."
DETECTIONS=$(timeout 5 mosquitto_sub -h localhost -t "nvr/detections/+" -C 1 2>/dev/null)
if [ -z "$DETECTIONS" ]; then
    echo "      ✅ NO hay detecciones (PAUSE funcionó)"
else
    echo "      ❌ SIGUEN llegando detecciones (PAUSE NO funcionó)"
    echo "      $DETECTIONS"
fi
echo ""

echo "   c) Enviando comando RESUME..."
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'
sleep 1

echo "   d) Verificando detecciones (deberían volver, timeout 5s)..."
DETECTIONS=$(timeout 5 mosquitto_sub -h localhost -t "nvr/detections/+" -C 1 2>/dev/null)
if [ -n "$DETECTIONS" ]; then
    echo "      ✅ Detecciones volvieron (RESUME funcionó)"
else
    echo "      ❌ NO hay detecciones (RESUME NO funcionó)"
fi
echo ""

echo "======================================================================="
echo "✅ Diagnóstico completado"
echo "======================================================================="
