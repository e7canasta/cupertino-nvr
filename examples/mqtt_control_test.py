#!/usr/bin/env python3
"""
MQTT Control Test Script
========================

Test script for demonstrating MQTT control plane functionality.
Sends various control commands to the processor and monitors status updates.

Usage:
    python mqtt_control_test.py [--broker localhost] [--port 1883]
"""

import argparse
import json
import time

import paho.mqtt.client as mqtt


class ControlPlaneTest:
    """Test client for MQTT control plane"""

    def __init__(self, broker_host="localhost", broker_port=1883):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.command_topic = "nvr/control/commands"
        self.status_topic = "nvr/control/status"

        # Setup MQTT client
        self.client = mqtt.Client(client_id="control_test_client")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.last_status = None

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            print(f"✅ Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            # Subscribe to status updates
            self.client.subscribe(self.status_topic, qos=1)
            print(f"📡 Subscribed to status topic: {self.status_topic}")
        else:
            print(f"❌ Connection failed with return code: {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        try:
            status_data = json.loads(msg.payload.decode())
            self.last_status = status_data
            print(f"\n📊 Status Update: {status_data['status']}")
            print(f"   Timestamp: {status_data.get('timestamp', 'N/A')}")
            print(f"   Client ID: {status_data.get('client_id', 'N/A')}")
        except Exception as e:
            print(f"⚠️  Error parsing status message: {e}")

    def connect(self):
        """Connect to MQTT broker"""
        print(f"Connecting to {self.broker_host}:{self.broker_port}...")
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()
        time.sleep(2)  # Wait for connection

    def disconnect(self):
        """Disconnect from broker"""
        self.client.loop_stop()
        self.client.disconnect()
        print("Disconnected from broker")

    def send_command(self, command):
        """Send a command to the processor"""
        payload = json.dumps({"command": command})
        print(f"\n📤 Sending command: {command}")
        self.client.publish(self.command_topic, payload, qos=1)
        time.sleep(1)  # Wait for response

    def run_test_sequence(self):
        """Run a test sequence of commands"""
        print("\n" + "=" * 70)
        print("🧪 MQTT Control Plane Test Sequence")
        print("=" * 70)

        # Test STATUS command
        print("\n### Test 1: Query Status ###")
        self.send_command("status")
        time.sleep(2)

        # Test PAUSE command
        print("\n### Test 2: Pause Processor ###")
        self.send_command("pause")
        time.sleep(3)

        # Verify paused
        print("\n### Test 3: Query Status (should be paused) ###")
        self.send_command("status")
        time.sleep(2)

        # Test RESUME command
        print("\n### Test 4: Resume Processor ###")
        self.send_command("resume")
        time.sleep(3)

        # Verify running
        print("\n### Test 5: Query Status (should be running) ###")
        self.send_command("status")
        time.sleep(2)

        # Test invalid command
        print("\n### Test 6: Invalid Command (should warn) ###")
        self.send_command("invalid_command")
        time.sleep(2)

        # Optional: Test STOP (commented out by default)
        # print("\n### Test 7: Stop Processor ###")
        # self.send_command("stop")
        # time.sleep(2)

        print("\n" + "=" * 70)
        print("✅ Test sequence completed")
        print("=" * 70)

    def interactive_mode(self):
        """Run in interactive mode"""
        print("\n" + "=" * 70)
        print("🎮 Interactive MQTT Control")
        print("=" * 70)
        print("\nAvailable commands:")
        print("  pause   - Pause stream processing")
        print("  resume  - Resume stream processing")
        print("  stop    - Stop processor (terminates)")
        print("  status  - Query current status")
        print("  quit    - Exit interactive mode")
        print()

        while True:
            try:
                command = input("Enter command: ").strip().lower()

                if command == "quit":
                    break
                elif command in ["pause", "resume", "stop", "status"]:
                    self.send_command(command)
                else:
                    print(f"⚠️  Unknown command: {command}")

            except KeyboardInterrupt:
                print("\n\nExiting...")
                break

        print("\nInteractive mode ended")


def main():
    parser = argparse.ArgumentParser(
        description="Test MQTT control plane for Cupertino NVR processor"
    )
    parser.add_argument(
        "--broker", default="localhost", help="MQTT broker host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=1883, help="MQTT broker port (default: 1883)"
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive mode",
    )
    args = parser.parse_args()

    # Create test client
    test = ControlPlaneTest(broker_host=args.broker, broker_port=args.port)

    try:
        # Connect to broker
        test.connect()

        # Run test sequence or interactive mode
        if args.interactive:
            test.interactive_mode()
        else:
            test.run_test_sequence()

    except KeyboardInterrupt:
        print("\n\nTest interrupted")
    finally:
        test.disconnect()


if __name__ == "__main__":
    main()

