FROM python:3.12-slim
WORKDIR /app
COPY main.py snippets.py ./
COPY static/ static/
RUN pip install fastapi uvicorn httpx pyjwt --no-cache-dir \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
