FROM python:3.13-slim AS deps

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Install CPU-only PyTorch first
RUN pip install --no-cache-dir torch==2.9.0+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir torchvision==0.24.0

# Install remaining dependencies
COPY ./requirements.txt /requirements.txt
RUN pip install -r /requirements.txt --no-cache-dir

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    jq \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=deps /usr/local/bin/ /usr/local/bin/

RUN mkdir /app
COPY . /app
WORKDIR /app
