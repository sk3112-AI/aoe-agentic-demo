# Use an official Python runtime as a base image.
# Debian Buster is generally well-suited for Playwright dependencies.
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required by Playwright browsers.
# These are the libraries that were missing on Render's native environment.
# --no-install-recommends helps keep the image size down.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-4-1 \
    libgraphene-1.0-0 \
    libgstgl-1.0-0 \
    gstreamer1.0-plugins-bad \
    libavif15 \
    libenchant-2-2 \
    libsecret-1-0 \
    libmanette-0.2-0 \
    libgles2-mesa \
    libnss3 \
    libatk-bridge2.0-0 \
    libxkbcommon0 \
    libdrm-dev \
    libgbm-dev \
    libasound2 \
    # Clean up apt caches to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy your requirements.txt file into the container
COPY requirements.txt .

# Install Python dependencies from requirements.txt
# --no-cache-dir reduces the size of the Docker image
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries
# This command downloads the actual browser executables (Chromium, Firefox, WebKit)
# It runs after system dependencies are installed
RUN playwright install

# Copy the rest of your application code into the container
COPY . .

# Expose the port that your FastAPI application will listen on
# Render typically exposes port 10000 for web services
EXPOSE 10000

# Define the command to run your FastAPI application
# This will be the main process when your Docker container starts
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]