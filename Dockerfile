FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-dan \
    tesseract-ocr-eng \
    ghostscript \
    qpdf \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app/ ./app/
COPY streamlit_app/ ./streamlit_app/
COPY prompts/ ./prompts/

RUN mkdir -p /app/storage

CMD streamlit run streamlit_app/Home.py \
    --server.port ${PORT:-8501} \
    --server.address 0.0.0.0 \
    --server.headless true
