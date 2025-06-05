# Use an official Python image with build tools
FROM python:3.12-slim

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    meson \
    ninja-build \
    libssl-dev \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-tools \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone and build Axis Signed Video Framework
RUN git clone https://github.com/AxisCommunications/signed-video-framework.git /tmp/signed-video-framework
WORKDIR /tmp/signed-video-framework

# Build and install the framework
RUN meson --prefix /usr/local . build && \
    ninja -C build && \
    ninja -C build install && \
    ldconfig

# Clone and build example applications
RUN git clone https://github.com/AxisCommunications/signed-video-framework-examples.git /tmp/signed-video-framework-examples
WORKDIR /tmp/signed-video-framework-examples

# Set GST_PLUGIN_PATH for GStreamer
ENV GST_PLUGIN_PATH=/usr/lib/x86_64-linux-gnu/gstreamer-1.0:/usr/local/lib/gstreamer-1.0

# Build signer and validator applications
RUN meson --prefix /usr/local -Dsigner=true -Dvalidator=true . build && \
    ninja -C build && \
    ninja -C build install

# Create directories for keys and temporary files
RUN mkdir -p /etc/video-signing /tmp/video-signing && \
    chmod 700 /etc/video-signing && \
    chmod 755 /tmp/video-signing

# Generate signing keys (for development - use secure key management in production)
RUN openssl genpkey -algorithm RSA -out /etc/video-signing/private.pem -pass pass:development_key_password -pkeyopt rsa_keygen_bits:2048 && \
    openssl rsa -pubout -in /etc/video-signing/private.pem -out /etc/video-signing/public.pem -passin pass:development_key_password && \
    chmod 600 /etc/video-signing/private.pem && \
    chmod 644 /etc/video-signing/public.pem
    

# Set working directory back to app
WORKDIR /app

# Copy Python requirements and install dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /tmp/video-signing && \
    chown appuser:appuser /etc/video-signing/public.pem
    # Note: Keep private.pem owned by root for security

# Environment variables
ENV SIGNED_VIDEO_LIB_PATH=/usr/local/lib/libsigned-video-framework.so
ENV SIGNER_EXECUTABLE=/usr/local/bin/signer
ENV VALIDATOR_EXECUTABLE=/usr/local/bin/validator
ENV PRIVATE_KEY_PATH=/etc/video-signing/private.pem
ENV PUBLIC_KEY_PATH=/etc/video-signing/public.pem
ENV TEMP_DIR=/tmp/video-signing
ENV DATABASE_URL=sqlite:///./signed_videos.db
ENV PRIVATE_KEY_PASSWORD=development_key_password

# Expose port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python3", "video_signing_backend.py"]
