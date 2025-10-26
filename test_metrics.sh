#!/bin/bash
#
# Test script para metrics reporting
#

echo "=================================================================="
echo "🧪 Testing Metrics Reporting"
echo "=================================================================="
echo ""

echo "1. Monitor periodic metrics (lightweight):"
echo "   mosquitto_sub -h localhost -t 'nvr/status/metrics' -v"
echo ""

echo "2. Query full metrics (on-demand):"
echo "   mosquitto_pub -h localhost -t 'nvr/control/commands' -m '{\"command\": \"metrics\"}'"
echo ""

echo "3. Monitor full metrics response:"
echo "   mosquitto_sub -h localhost -t 'nvr/control/status/metrics' -v"
echo ""

echo "=================================================================="
echo "Expected behavior:"
echo "=================================================================="
echo ""
echo "• Periodic (nvr/status/metrics):"
echo "  - Published every 10 seconds (default)"
echo "  - Lightweight: throughput + avg latency + per-source latency"
echo "  - Retained (new subscribers get last value)"
echo ""
echo "• On-demand (nvr/control/status/metrics):"
echo "  - Published only when 'metrics' command received"
echo "  - Full detail: latencies, sources metadata, errors"
echo "  - Not retained (one-time response)"
echo ""

echo "=================================================================="
echo "Monitoring periodic metrics..."
echo "=================================================================="
echo ""

mosquitto_sub -h localhost -t "nvr/status/metrics" -v
