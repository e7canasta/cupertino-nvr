#!/bin/bash
# Test script for Dynamic Configuration Commands
# Usage: ./test_dynamic_config.sh

set -e

MQTT_HOST="localhost"
COMMAND_TOPIC="nvr/control/commands"

echo "🧪 Testing Dynamic Configuration Commands"
echo "=========================================="
echo ""

# Helper function
send_command() {
    local cmd=$1
    echo "📤 $cmd"
    mosquitto_pub -h "$MQTT_HOST" -t "$COMMAND_TOPIC" -m "$cmd"
    sleep 3
}

echo "Prerequisites:"
echo "1. Start processor: uv run cupertino-nvr processor --streams 0 --enable-control --max-fps 0.1 --model yolov11s-640"
echo "2. Monitor status: mosquitto_sub -h localhost -t 'nvr/control/status' -v"
echo ""
read -p "Press ENTER when ready..."
echo ""

echo "Test 1: CHANGE_MODEL (yolov11s-640 → yolov11x-640)"
echo "===================================================="
send_command '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'
echo "✅ Expected: Status 'reconfiguring' → 'running', detections use yolov11x-640"
echo ""

echo "Test 2: SET_FPS (0.1 → 1.0)"
echo "============================"
send_command '{"command": "set_fps", "params": {"max_fps": 1.0}}'
echo "✅ Expected: Status 'reconfiguring' → 'running', inference at 1 FPS"
echo ""

echo "Test 3: ADD_STREAM (add habitación 8)"
echo "======================================"
send_command '{"command": "add_stream", "params": {"source_id": 8}}'
echo "✅ Expected: Status 'reconfiguring' → 'running', detections for source_id 0 AND 8"
echo "✅ Stream URI auto-generated: rtsp://go2rtc-server/8"
echo ""

echo "Test 4: REMOVE_STREAM (remove habitación 0)"
echo "============================================"
send_command '{"command": "remove_stream", "params": {"source_id": 0}}'
echo "✅ Expected: Status 'reconfiguring' → 'running', only detections for source_id 1"
echo ""

echo "Test 5: SET_FPS back to 0.1 (reduce load)"
echo "=========================================="
send_command '{"command": "set_fps", "params": {"max_fps": 0.1}}'
echo "✅ Expected: Status 'reconfiguring' → 'running', inference slows down"
echo ""

echo "Test 6: Error handling (invalid model)"
echo "======================================="
send_command '{"command": "change_model", "params": {"model_id": "invalid-model"}}'
echo "✅ Expected: ACK 'error', status 'error', config rolled back"
echo ""

echo "Test 7: Error handling (missing params)"
echo "========================================"
send_command '{"command": "change_model", "params": {}}'
echo "✅ Expected: ACK 'error', ValueError about missing model_id"
echo ""

echo ""
echo "🏁 Manual Testing Complete"
echo ""
echo "Check logs for structured events:"
echo "  - change_model_command_start, change_model_completed"
echo "  - set_fps_command_start, set_fps_completed"
echo "  - add_stream_command_start, add_stream_completed"
echo "  - remove_stream_command_start, remove_stream_completed"
echo ""
echo "Verify rollback on errors:"
echo "  - Config should revert to previous state on failure"
echo "  - Error logs should show 'rolled_back_to'"
echo ""
