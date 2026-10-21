# Official Playwright image: Python + Chromium + all system deps preinstalled.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
# Default: the Streamlit UI. Override for the CLI, e.g. `docker run --rm ui-parity-agent python -m parity_agent run --demo`.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
