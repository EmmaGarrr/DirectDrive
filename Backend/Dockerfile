# Use a modern, slim Python base image
FROM python:3.10-slim

# Set environment variables for best practices
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies, including supervisord
RUN apt-get update && apt-get install -y supervisor && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- NEW: Add a failsafe to ensure old code is gone ---
# This command deletes everything in /app before copying the new code,
# preventing any stale files from lingering in a cached layer.
RUN rm -rf /app/*
# --- END OF NEW ---

# Copy the entire backend application code into the container
COPY . .

# Copy the supervisor configuration file into the location where supervisor looks for it
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the port your Uvicorn server will run on
EXPOSE 5000

# The command that will be run when the container starts.
# It starts supervisord, which in turn starts and manages all your processes.
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]