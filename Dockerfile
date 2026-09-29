FROM python:3.14-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

FROM python:3.14-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=base /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=base /usr/local/bin/subdomain-enum /usr/local/bin/subdomain-enum
COPY src ./src

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data && chown appuser:appuser /data
USER appuser
VOLUME ["/data"]
WORKDIR /data

ENTRYPOINT ["subdomain-enum"]
CMD ["--help"]
