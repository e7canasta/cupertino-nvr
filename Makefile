# Makefile for Cupertino NVR
# ==========================

.PHONY: help install install-dev test test-unit test-integration lint format clean run-processor run-wall docker-build docker-run

# Variables
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
BLACK := $(VENV)/bin/black
ISORT := $(VENV)/bin/isort
FLAKE8 := $(VENV)/bin/flake8
MYPY := $(VENV)/bin/mypy

# Check if venv exists
VENV_EXISTS := $(shell [ -d $(VENV) ] && echo 1 || echo 0)

# Docker
DOCKER_IMAGE := cupertino/nvr
DOCKER_TAG := latest

# Default target
help:
	@echo "Cupertino NVR - Makefile Commands"
	@echo "=================================="
	@echo ""
	@echo "Installation:"
	@echo "  make install          Install package"
	@echo "  make install-dev      Install package in dev mode with dev dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make format           Format code with black and isort"
	@echo "  make lint             Run linters (flake8, mypy)"
	@echo "  make test             Run all tests"
	@echo "  make test-unit        Run unit tests only"
	@echo "  make test-integration Run integration tests only"
	@echo "  make coverage         Run tests with coverage report"
	@echo ""
	@echo "Running:"
	@echo "  make run-processor    Run stream processor (headless)"
	@echo "  make run-wall         Run video wall viewer"
	@echo "  make run-broker       Run MQTT broker (Docker)"
	@echo "  make run-streams      Run RTSP test streams (go2rtc)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     Build Docker image"
	@echo "  make docker-run       Run in Docker container"
	@echo "  make docker-clean     Remove Docker images"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            Remove build artifacts and cache"
	@echo "  make clean-all        Deep clean (including venv)"

# Installation
$(VENV):
	@echo "Creating virtual environment..."
	@python3 -m venv $(VENV)
	@$(PIP) install --upgrade pip setuptools wheel
	@echo "Virtual environment created at $(VENV)"
	@echo "Activate with: source $(VENV)/bin/activate"

install: $(VENV)
	@echo "Installing package..."
	@$(PIP) install -e .

install-dev: $(VENV)
	@echo "Installing package in development mode..."
	@$(PIP) install -e ".[dev]"

# Development
format:
	@echo "Formatting code..."
	$(BLACK) --line-length 88 .
	$(ISORT) --profile black .

lint:
	@echo "Running linters..."
	$(FLAKE8) --max-line-length 88 --extend-ignore E203,W503 cupertino/
	$(MYPY) cupertino/ --ignore-missing-imports

test:
	@echo "Running all tests..."
	$(PYTEST) tests/ -v

test-unit:
	@echo "Running unit tests..."
	$(PYTEST) tests/unit/ -v

test-integration:
	@echo "Running integration tests..."
	$(PYTEST) tests/integration/ -v --tb=short

coverage:
	@echo "Running tests with coverage..."
	$(PYTEST) tests/ --cov=cupertino.nvr --cov-report=html --cov-report=term
	@echo "Coverage report generated in htmlcov/index.html"

# Running
run-processor:
	@echo "Starting StreamProcessor..."
	@echo "Streams: $(or $(N),6)"
	@echo "Model: $(or $(MODEL),yolov8x-640)"
	@echo "MQTT: $(or $(MQTT_HOST),localhost):$(or $(MQTT_PORT),1883)"
	$(PYTHON) -m cupertino.nvr.cli processor \
		--n $(or $(N),6) \
		--model $(or $(MODEL),yolov8x-640) \
		--mqtt-host $(or $(MQTT_HOST),localhost) \
		--mqtt-port $(or $(MQTT_PORT),1883)

run-wall:
	@echo "Starting VideoWall..."
	@echo "Streams: $(or $(N),6)"
	@echo "MQTT: $(or $(MQTT_HOST),localhost):$(or $(MQTT_PORT),1883)"
	$(PYTHON) -m cupertino.nvr.cli wall \
		--n $(or $(N),6) \
		--mqtt-host $(or $(MQTT_HOST),localhost) \
		--mqtt-port $(or $(MQTT_PORT),1883)

run-broker:
	@echo "Starting MQTT broker..."
	docker run -d --name mosquitto \
		-p 1883:1883 \
		-p 9001:9001 \
		eclipse-mosquitto
	@echo "MQTT broker running on port 1883"

run-streams:
	@echo "Starting RTSP test streams..."
	@if [ ! -f go2rtc ]; then \
		echo "go2rtc not found. Download from https://github.com/AlexxIT/go2rtc/releases"; \
		exit 1; \
	fi
	./go2rtc -config ../../../config/go2rtc/go2rtc.yaml

stop-broker:
	@echo "Stopping MQTT broker..."
	docker stop mosquitto || true
	docker rm mosquitto || true

# Docker
docker-build:
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) -f Dockerfile .

docker-run:
	@echo "Running in Docker..."
	docker run -it --rm \
		-e MQTT_HOST=$(or $(MQTT_HOST),host.docker.internal) \
		-p 8080:8080 \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

docker-clean:
	@echo "Cleaning Docker images..."
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG) || true

# Cleanup
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

clean-all: clean
	@echo "Deep cleaning..."
	rm -rf venv/
	rm -rf .venv/

# Quick start helpers
demo: run-broker
	@echo "Waiting for broker to start..."
	@sleep 2
	@echo ""
	@echo "==================================="
	@echo "Quick Start Demo"
	@echo "==================================="
	@echo ""
	@echo "1. Open a new terminal and run:"
	@echo "   cd cupertino/nvr && make run-processor N=4"
	@echo ""
	@echo "2. Open another terminal and run:"
	@echo "   cd cupertino/nvr && make run-wall N=4"
	@echo ""
	@echo "3. Monitor MQTT events:"
	@echo "   mosquitto_sub -t 'nvr/detections/#' -v"
	@echo ""
	@echo "Press Ctrl+C to stop the broker"
	@docker logs -f mosquitto

# Development helpers
dev-setup: $(VENV) install-dev
	@echo "Development environment ready!"
	@echo "Activate with: source $(VENV)/bin/activate"

watch-tests:
	@echo "Watching for changes and running tests..."
	$(PYTEST) tests/ -v --looponfail

# CI/CD
ci: lint test coverage
	@echo "CI pipeline completed successfully"

# Documentation
docs:
	@echo "Opening documentation..."
	@if [ -f "../../../wiki/NVR_INDEX.md" ]; then \
		cat ../../../wiki/NVR_INDEX.md; \
	else \
		echo "Documentation not found. See ../../../wiki/NVR_*.md"; \
	fi

# Version bump
bump-patch:
	@echo "Bumping patch version..."
	@$(PYTHON) -c "import re; \
		content = open('__init__.py').read(); \
		new = re.sub(r'__version__ = \"(\d+)\.(\d+)\.(\d+)\"', \
			lambda m: f'__version__ = \"{m.group(1)}.{m.group(2)}.{int(m.group(3))+1}\"', \
			content); \
		open('__init__.py', 'w').write(new); \
		print('Version bumped')"

bump-minor:
	@echo "Bumping minor version..."
	@$(PYTHON) -c "import re; \
		content = open('__init__.py').read(); \
		new = re.sub(r'__version__ = \"(\d+)\.(\d+)\.(\d+)\"', \
			lambda m: f'__version__ = \"{m.group(1)}.{int(m.group(2))+1}.0\"', \
			content); \
		open('__init__.py', 'w').write(new); \
		print('Version bumped')"

bump-major:
	@echo "Bumping major version..."
	@$(PYTHON) -c "import re; \
		content = open('__init__.py').read(); \
		new = re.sub(r'__version__ = \"(\d+)\.(\d+)\.(\d+)\"', \
			lambda m: f'__version__ = \"{int(m.group(1))+1}.0.0\"', \
			content); \
		open('__init__.py', 'w').write(new); \
		print('Version bumped')"

