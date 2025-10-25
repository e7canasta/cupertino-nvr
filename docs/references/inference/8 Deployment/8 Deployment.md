

# Deployment

Relevant source files

- [docker/dockerfiles/Dockerfile.onnx.cpu](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu)
- [docker/dockerfiles/Dockerfile.onnx.cpu.dev](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu.dev)
- [docker/dockerfiles/Dockerfile.onnx.cpu.parallel](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu.parallel)
- [docker/dockerfiles/Dockerfile.onnx.cpu.slim](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu.slim)
- [docker/dockerfiles/Dockerfile.onnx.cpu.stream_manager](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu.stream_manager)
- [docker/dockerfiles/Dockerfile.onnx.lambda](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.lambda)
- [docker/dockerfiles/Dockerfile.onnx.lambda.slim](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.lambda.slim)
- [docker/dockerfiles/Dockerfile.stream_management_api](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.stream_management_api)

This page provides an overview of the various deployment options and configurations for Roboflow Inference. It covers how to deploy the Inference server in different environments, from local machines to cloud platforms, and how to optimize for various hardware configurations.

For specific instructions on Docker deployment, see [Docker Deployment](https://deepwiki.com/roboflow/inference/4.1-inferencepipeline). For details on hardware support and optimization, see [Hardware Support](https://deepwiki.com/roboflow/inference/4.2-video-sources-and-multiplexing).

## Deployment Overview

Roboflow Inference is designed to run on a wide range of hardware from powerful cloud servers to edge devices. This flexibility allows you to develop against your local machine or cloud infrastructure and then seamlessly transition to another device for production deployment.

The primary deployment method is via Docker containers, which ensures consistent environments across different systems. You can deploy Inference in several ways:

1. **Self-hosted deployment** - Running on your own hardware
    
    - Local machines (Windows, Mac, Linux)
    - Edge devices (Raspberry Pi)
    - On-premises servers
2. **Cloud deployment** - Running on cloud infrastructure
    - AWS Lambda
    - AWS EC2
    - Azure
    - Google Cloud Platform
    - Custom cloud environments
3. **Hosted compute** - Using Roboflow's infrastructure
    - Serverless Hosted API
    - Dedicated Deployments

Sources: [README.md280-288](https://github.com/roboflow/inference/blob/55f57676/README.md#L280-L288) [mkdocs.yml170-179](https://github.com/roboflow/inference/blob/55f57676/mkdocs.yml#L170-L179)

## Deployment Architecture

The Inference server can be deployed in multiple configurations depending on your needs. The diagram below shows the high-level deployment architecture:

## Docker-based Deployment

The primary deployment method for Inference is through Docker containers. Roboflow provides various Docker images optimized for different hardware configurations.

### Available Docker Images

The following table lists the available Docker images:

| Image                                    | Description             | Use Case                                       |
| ---------------------------------------- | ----------------------- | ---------------------------------------------- |
| `roboflow/roboflow-inference-server-cpu` | CPU-optimized container | General-purpose deployment, x86 and ARM64 CPUs |
| `roboflow-inference-server-cpu-slim`     | Minimal CPU container   | Lightweight deployment                         |


### Deployment Workflow

The diagram below illustrates the typical workflow for deploying the Inference server:

Sources: [README.md47-65](https://github.com/roboflow/inference/blob/55f57676/README.md#L47-L65) [inference_cli/README.md30-43](https://github.com/roboflow/inference/blob/55f57676/inference_cli/README.md#L30-L43)

## Self-hosted Deployment

Self-hosted deployment allows you to run the Inference server on your own hardware. This gives you complete control over the infrastructure and allows for customization based on your specific needs.

### Using the CLI

The easiest way to start a self-hosted Inference server is by using the Inference CLI:

```
pip install inference-cli
inference server start
```

This command automatically detects your hardware and pulls the appropriate Docker image. By default, the server will run on port 9001.

Additional CLI options:

- `--port` - Specify a custom port (default: 9001)
- `--env-file` - Specify a file with environment variables
- `--dev` - Start in development mode with a Jupyter notebook server

Sources: [README.md45-65](https://github.com/roboflow/inference/blob/55f57676/README.md#L45-L65) [inference_cli/README.md32-47](https://github.com/roboflow/inference/blob/55f57676/inference_cli/README.md#L32-L47) [docs/quickstart/docker.md7-19](https://github.com/roboflow/inference/blob/55f57676/docs/quickstart/docker.md#L7-L19)

### Manual Docker Setup

You can also manually set up Docker containers for more control over the deployment:

```
# For CPU deployment
docker run -it --net=host roboflow/roboflow-inference-server-cpu:latest

```

Additional Docker run options:

- `-e ROBOFLOW_API_KEY=<YOUR API KEY>` - Set your Roboflow API key
- `-v $(pwd)/cache:/tmp/cache` - Create a cache folder for model artifacts
- `-v inference-cache:/tmp/cache` - Use a Docker volume for cache

Sources: [docs/quickstart/docker.md101-145](https://github.com/roboflow/inference/blob/55f57676/docs/quickstart/docker.md#L101-L145) [docker/dockerfiles/Dockerfile.onnx.gpu90-105](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.gpu#L90-L105)

## Hardware-specific Deployments

Roboflow Inference supports various hardware configurations, each with optimized Docker images and configurations.

### Hardware Support Matrix

The following table shows the supported hardware platforms and their corresponding Docker images:

| Hardware                 | Docker Image                             | Execution Provider | Performance                 |
| ------------------------ | ---------------------------------------- | ------------------ | --------------------------- |
| x86 CPU                  | `roboflow-inference-server-cpu`          | CPU                | Good for development        |
| ARM64 CPU                | `roboflow-inference-server-cpu`          | CPU                | Good for small edge devices |


### 
## Cloud Deployment

Roboflow Inference can be deployed on various cloud platforms, with special support for AWS Lambda for serverless deployments.

### AWS Lambda Deployment

The AWS Lambda deployment uses a specialized container optimized for the Lambda environment:

The Lambda container is configured with specific environment variables optimized for serverless execution:

```
ENV LAMBDA=True
ENV CORE_MODEL_SAM_ENABLED=False
ENV CORE_MODEL_SAM2_ENABLED=False
ENV ALLOW_NUMPY_INPUT=False
ENV INFERENCE_SERVER_ID=HostedInferenceLambda
ENV DISABLE_VERSION_CHECK=true
ENV DOCTR_MULTIPROCESSING_DISABLE=TRUE
ENV REDIS_SSL=true
ENV WORKFLOWS_STEP_EXECUTION_MODE=remote
ENV WORKFLOWS_REMOTE_API_TARGET=hosted
ENV API_LOGGING_ENABLED=True
ENV MODEL_VALIDATION_DISABLED=True
```

Sources: [docker/dockerfiles/Dockerfile.onnx.lambda59-81](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.lambda#L59-L81) [docker/dockerfiles/Dockerfile.onnx.lambda.slim51-75](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.lambda.slim#L51-L75)

### Other Cloud Platforms

Inference can be deployed on various cloud platforms using the standard Docker containers. Key considerations for cloud deployment:

1. Select the appropriate container based on available hardware (CPU/GPU)
2. Configure networking to expose the Inference server
3. Set up appropriate security settings
4. Consider using managed Kubernetes services for scaling

## Roboflow Hosted Options

If you don't want to manage your own infrastructure, Roboflow offers hosted options:

1. **Dedicated Deployments** - One-click deployments of dedicated Inference servers (CPU or GPU) billed hourly
2. **Serverless Hosted API** - Simple models and workflows via serverless API billed per API call

The Roboflow hosted services offer the same functionality as self-hosted deployments but with the added benefit of managed infrastructure.

Sources: [README.md280-284](https://github.com/roboflow/inference/blob/55f57676/README.md#L280-L284) [mkdocs.yml42-46](https://github.com/roboflow/inference/blob/55f57676/mkdocs.yml#L42-L46)

## Configuration Options

Inference servers can be configured using environment variables. Here are the key configuration options:

|Environment Variable|Description|Default|
|---|---|---|
|`NUM_WORKERS`|Number of worker processes|1|
|`HOST`|Host address to bind|0.0.0.0|
|`PORT`|Port to listen on|9001|
|`ROBOFLOW_API_KEY`|Roboflow API key for accessing models|None|
|`ONNXRUNTIME_EXECUTION_PROVIDERS`|ONNX Runtime execution provider|Depends on image|
|`ORT_TENSORRT_ENGINE_CACHE_ENABLE`|Enable TensorRT engine caching|1 (for TensorRT images)|
|`CORE_MODEL_SAM_ENABLED`|Enable SAM model|True (except on resource-constrained platforms)|
|`CORE_MODEL_SAM2_ENABLED`|Enable SAM2 model|True (except on resource-constrained platforms)|
|`WORKFLOWS_STEP_EXECUTION_MODE`|Workflow execution mode|local|
|`WORKFLOWS_MAX_CONCURRENT_STEPS`|Maximum concurrent workflow steps|4|
|`API_LOGGING_ENABLED`|Enable API logging|True|
|`ENABLE_STREAM_API`|Enable stream processing API|True (except Lambda)|
|`STREAM_API_PRELOADED_PROCESSES`|Preloaded processes for stream API|2|

Sources: [docker/dockerfiles/Dockerfile.onnx.gpu90-104](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.gpu#L90-L104) [docker/dockerfiles/Dockerfile.onnx.cpu68-79](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu#L68-L79) [docker/dockerfiles/Dockerfile.onnx.trt55-71](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.trt#L55-L71) [docker/dockerfiles/Dockerfile.onnx.jetson.5.1.172-92](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.jetson.5.1.1#L72-L92)

## Advanced Deployment Features

### Parallel Processing

For high-throughput scenarios, Inference offers parallel processing with the `parallel_http` configuration:

Sources: [docker/dockerfiles/Dockerfile.onnx.gpu.parallel58-71](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.gpu.parallel#L58-L71) [docker/dockerfiles/Dockerfile.onnx.cpu.parallel64-86](https://github.com/roboflow/inference/blob/55f57676/docker/dockerfiles/Dockerfile.onnx.cpu.parallel#L64-L86)

### Stream Management

For video stream processing, the Stream Management API allows for managing inference pipelines:

Sources: [docs/quickstart/run_model_on_rtsp_webcam.md22-53](https://github.com/roboflow/inference/blob/55f57676/docs/quickstart/run_model_on_rtsp_webcam.md#L22-L53) [docs/using_inference/native_python_api.md34-73](https://github.com/roboflow/inference/blob/55f57676/docs/using_inference/native_python_api.md#L34-L73)

## Conclusion

Roboflow Inference offers a flexible and powerful deployment system that can adapt to various hardware configurations and deployment environments. Whether you're running on a powerful GPU server, an edge device, or in the cloud, Inference provides optimized containers and configurations to ensure the best performance for your computer vision models.

For specific deployment scenarios or advanced configuration options, refer to the documentation links throughout this page or contact the Roboflow team for support.

Sources: [README.md288-284](https://github.com/roboflow/inference/blob/55f57676/README.md#L288-L284) [mkdocs.yml119-123](https://github.com/roboflow/inference/blob/55f57676/mkdocs.yml#L119-L123)