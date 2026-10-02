FROM python:3.12-slim
WORKDIR /app
COPY runner.py .
RUN pip install fastapi uvicorn pyjwt --no-cache-dir \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app \
    && mkdir -p /workspace && chown appuser /workspace
USER appuser
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "8080"]
