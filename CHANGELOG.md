# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-25

### 🚀 Added

#### Core Architecture
- **MQTT-based Control Plane**: Complete remote orchestration system for processor instances
- **Dynamic Model Switching**: Runtime model changes via `switch_model` command without restart
- **Instance Discovery**: Automatic processor discovery with heartbeat pattern
- **Event-Driven Architecture**: Pub/sub messaging for scalable, decoupled components

#### Control & Management
- **Pipeline Lifecycle Control**: Start, stop, restart, and status commands via MQTT
- **Real-time Metrics Collection**: Performance tracking with FPS, detection counts, and latency
- **Structured Logging**: JSON-formatted logs with configurable levels and rotation
- **Configuration Management**: Centralized, type-safe configuration with Pydantic schemas

#### Infrastructure
- **Process Isolation**: Independent processor instances with resource management  
- **Graceful Shutdown**: Signal handling for clean termination and resource cleanup
- **Error Recovery**: Comprehensive error handling with automatic recovery mechanisms
- **GO2RTC Integration**: Proxy patterns for stream management and load balancing

#### Developer Experience
- **CLI Interface**: Enhanced command-line tools with `--control-plane` mode
- **Debug Utilities**: Comprehensive debugging scripts and troubleshooting tools
- **Documentation Suite**: Complete architectural blueprints and quick reference guides
- **Test Framework**: Functional test cases and integration scenarios

### 📁 Project Structure

```
cupertino-nvr/
├── cupertino_nvr/
│   ├── processor/
│   │   ├── control_plane.py     # MQTT control orchestration
│   │   ├── config.py           # Configuration management  
│   │   └── mqtt_sink.py        # Enhanced event publishing
│   ├── events/
│   │   └── schema.py           # Event schemas with metrics
│   ├── logging_utils.py        # Structured logging utilities
│   └── cli.py                  # Enhanced CLI with control plane
├── config/
│   └── go2rtc/                 # GO2RTC proxy configuration
├── docs/nvr/                   # Architecture documentation
│   ├── BLUEPRINT_INFERENCE_PIPELINE_CONTROL.md
│   ├── QUICK_REFERENCE_CONTROL_PLANE.md
│   └── GO2RTC_PROXY_ARCHITECTURE.md
└── vendors/inference/          # Roboflow Inference integration
```

### 🔧 Technical Specifications

- **Python**: 3.9+
- **MQTT Protocol**: QoS 0 for real-time performance
- **Message Format**: JSON with Pydantic validation
- **Logging**: Structured JSON with rotation support
- **Dependencies**: Minimal external dependencies, production-ready

### 🎯 Key Features

#### MQTT Control Commands
```bash
# Model management
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "switch_model", "model_id": "yolov8x-1280"}'

# Pipeline control  
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "start"}'
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "stop"}'
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "restart"}'

# Status and metrics
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "status"}'
mosquitto_pub -t "nvr/control/processor_1" -m '{"command": "get_metrics"}'
```

#### Performance Metrics
- **FPS Tracking**: Real-time frames per second monitoring
- **Detection Counts**: Object detection statistics per stream
- **Latency Measurements**: End-to-end processing time tracking
- **Resource Usage**: Memory and CPU utilization metrics

### 🏗️ Architecture Highlights

- **Separation of Concerns**: Clean bounded contexts between processor, wall, and events
- **Event-Driven Design**: Asynchronous messaging for scalability
- **Dynamic Orchestration**: Runtime reconfiguration without service disruption
- **Observability**: Comprehensive logging and metrics for production monitoring

### 🧪 Testing & Quality

- **Functional Test Cases**: Complete scenario coverage in `TEST_CASES_FUNCIONALES.md`
- **Integration Testing**: End-to-end workflow validation
- **Error Handling**: Robust exception management and recovery
- **Documentation**: Comprehensive guides for development and operations

### 📚 Documentation

- **Quick Reference**: `docs/nvr/QUICK_REFERENCE_CONTROL_PLANE.md`
- **Architecture Blueprints**: Complete system design documentation  
- **Troubleshooting Guides**: Common issues and solutions
- **API Documentation**: MQTT protocol and command reference

### 🔮 What's Next

See `backlog/` directory for planned features and enhancements.

---

**Full Changelog**: https://github.com/e7canasta/cupertino-nvr/compare/v0.0.0...v0.1.0

**Contributors**: 
- Co-Authored-By: Gaby <noreply@visiona.com>