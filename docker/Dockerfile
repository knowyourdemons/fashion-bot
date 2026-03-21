FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /root/.u2net && \
    curl -fSL -o /root/.u2net/silueta.onnx \
    https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx && \
    curl -fSL -o /root/.u2net/rmbg14_quantized.onnx \
    https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model_quantized.onnx
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
