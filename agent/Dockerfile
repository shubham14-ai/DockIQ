FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent package (so `python -m agent.main` resolves imports).
COPY __init__.py main.py nats_publisher.py commands.py ./agent/
COPY collectors/ ./agent/collectors/

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "agent.main"]
