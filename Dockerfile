# Use a lightweight Python image
FROM python:3.12-slim-bookworm

# Install system dependencies (FFmpeg is crucial)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY main.py .

# Create the data directory
RUN mkdir -p /data

# Run the server
CMD ["python", "main.py"]
