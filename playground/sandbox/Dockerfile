# Used for local dev/testing. Production builds use the inline dockerfile in build-config.json.
FROM python:3.12-slim
WORKDIR /app
COPY runner.py .
RUN pip install fastapi uvicorn pyjwt --no-cache-dir
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "8080"]
