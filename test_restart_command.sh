#!/bin/bash
# Test script for RESTART command
# Usage: ./test_restart_command.sh

set -e

MQTT_HOST="localhost"
MQTT_PORT="1883"
COMMAND_TOPIC="nvr/control/commands"
STATUS_TOPIC="nvr/control/status"
ACK_TOPIC="nvr/control/status/ack"

echo "🧪 Testing RESTART Command"
echo "=========================="
echo ""

# Function to send command
send_command() {
    local cmd=$1
    echo "📤 Sending command: $cmd"
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$COMMAND_TOPIC" -m "$cmd"
}

# Function to subscribe to topic
subscribe_topic() {
    local topic=$1
    echo "📥 Subscribing to: $topic"
    mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$topic" -v -C 5 &
}

echo "Step 1: Subscribe to Status and ACK topics"
echo "==========================================="
echo ""

# Subscribe to status (background)
echo "Status updates:"
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$STATUS_TOPIC" -v &
STATUS_PID=$!

sleep 1

echo ""
echo "ACK updates:"
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$ACK_TOPIC" -v &
ACK_PID=$!

sleep 2

echo ""
echo "Step 2: Send RESTART command"
echo "============================"
send_command '{"command": "restart"}'

echo ""
echo "⏳ Waiting for restart to complete (30 seconds)..."
sleep 30

echo ""
echo "Step 3: Verify status is 'running'"
echo "==================================="
CURRENT_STATUS=$(mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "$STATUS_TOPIC" -C 1 | jq -r '.status')
echo "Current status: $CURRENT_STATUS"

if [ "$CURRENT_STATUS" == "running" ]; then
    echo "✅ Test PASSED - Processor is running after restart"
else
    echo "❌ Test FAILED - Expected 'running', got '$CURRENT_STATUS'"
fi

echo ""
echo "Step 4: Test idempotency (restart during restart)"
echo "=================================================="
send_command '{"command": "restart"}'
sleep 1
send_command '{"command": "restart"}'  # Should be rejected

echo ""
echo "⏳ Waiting 5 seconds for rejection message..."
sleep 5

echo ""
echo "Step 5: Send STATUS query"
echo "========================="
send_command '{"command": "status"}'
sleep 2

echo ""
echo "🏁 Test complete"
echo ""

# Cleanup background processes
kill $STATUS_PID $ACK_PID 2>/dev/null || true

echo "To monitor full test manually, run these in separate terminals:"
echo ""
echo "  Terminal 1: uv run cupertino-nvr processor --streams 0 --enable-control --max-fps 0.1"
echo "  Terminal 2: mosquitto_sub -h localhost -t 'nvr/control/status' -v"
echo "  Terminal 3: mosquitto_sub -h localhost -t 'nvr/control/status/ack' -v"
echo "  Terminal 4: mosquitto_pub -h localhost -t 'nvr/control/commands' -m '{\"command\": \"restart\"}'"
echo ""
