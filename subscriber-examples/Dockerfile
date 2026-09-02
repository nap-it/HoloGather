# Override this at build time when a project-specific base image is required.
# Keep the default on a public image so a fresh GitHub checkout is buildable.
# Pinned multi-platform Ubuntu 22.04 image index for reproducible release builds.
# Override BASE_IMAGE deliberately when applying base-image security updates.
ARG BASE_IMAGE=ubuntu:22.04@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# ------------------------------------------------------------------------------
# 1) SYSTEM DEPENDENCIES
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    iproute2 \
    net-tools \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libglib2.0-dev \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root/app/

# ------------------------------------------------------------------------------
# 2) APPLICATION PYTHON DEPENDENCIES
# ------------------------------------------------------------------------------
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# ------------------------------------------------------------------------------
# 3) APPLICATION SETUP
# ------------------------------------------------------------------------------
# Copy static libraries
RUN mkdir -p /root/app/libs 
COPY libs /root/app/libs

# Copy source code
RUN mkdir -p /root/app/src
COPY src /root/app/src

# Copy configuration files
RUN mkdir -p /root/app/configs
COPY configs /root/app/configs

# Copy entrypoint script
COPY scripts/subscriber-start.sh .
RUN chmod +x subscriber-start.sh

ENTRYPOINT ["subscriber-start.sh"]
