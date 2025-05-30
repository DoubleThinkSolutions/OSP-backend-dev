# Use an official Python image with build tools
FROM ubuntu:25.10

# Set non-interactive frontend
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository universe

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    meson \
    ninja-build \
    libssl-dev \
    pkg-config \
    python3 \
    python3-pip \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    git \
    openssl \
    curl \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Clone and build signed-video-framework
WORKDIR /opt
RUN git clone https://github.com/AxisCommunications/signed-video-framework.git && \
    cd signed-video-framework && \
    meson --prefix /usr/local . build && \
    ninja -C build && \
    ninja -C build install

# Clone and build signer example
RUN git clone https://github.com/AxisCommunications/signed-video-framework-examples.git && \
    cd signed-video-framework-examples && \
    meson --prefix /usr/local -Dsigner=true . build && \
    ninja -C build && \
    ninja -C build install

# Set up signing keys
RUN mkdir -p /etc/video-signing && \
    chmod 700 /etc/video-signing && \
    openssl genpkey -algorithm RSA -out /etc/video-signing/private.pem -pass pass:dummy -pkeyopt rsa_keygen_bits:2048 && \
    openssl rsa -pubout -in /etc/video-signing/private.pem -out /etc/video-signing/public.pem -passin pass:dummy && \
    chmod 600 /etc/video-signing/private.pem && \
    chmod 644 /etc/video-signing/public.pem

# Create temp dir
RUN mkdir -p /tmp/video-signing && chmod 755 /tmp/video-signing

# Copy backend source
COPY . /app
WORKDIR /app

# Install Python dependencies
# Set up venv
RUN python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# Optionally, add to PATH
ENV PATH="/venv/bin:$PATH"


# Add .env with dummy values (you should mount a real one in production)
RUN echo "\
DATABASE_URL=sqlite:///./signed_videos.db\n\
SIGNED_VIDEO_LIB_PATH=/usr/local/lib/libsigned-video-framework.so\n\
SIGNER_EXECUTABLE=/usr/local/bin/signer\n\
PRIVATE_KEY_PATH=/etc/video-signing/private.pem\n\
TEMP_DIR=/tmp/video-signing\n\
HOST=0.0.0.0\n\
PORT=8000\n\
DEBUG=false" > .env

# Expose port
EXPOSE 8000

# Start the backend
CMD ["python3", "video_signing_backend.py"]
