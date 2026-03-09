# IDI — Intent-Driven Infrastructure compiler
# Dual-mode: "web" → FastAPI on :8090, default → CLI
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -m -s /bin/bash platform

WORKDIR /app
COPY platform-tools/idi/pyproject.toml /app/
COPY platform-tools/idi/idi/ /app/idi/

RUN pip install --no-cache-dir /app

# Entrypoint: "web" → uvicorn, default → CLI
RUN printf '#!/bin/bash\ncase "$1" in\n  web)\n    shift\n    exec uvicorn idi.enrichment.app:app --host 0.0.0.0 --port 8090 "$@"\n    ;;\n  generate)\n    shift\n    exec idi-generate "$@"\n    ;;\n  download)\n    shift\n    exec idi-download "$@"\n    ;;\n  *)\n    exec "$@"\n    ;;\nesac\n' > /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

RUN mkdir -p /output /data /data/specs /data/skills \
    && chown -R platform:platform /output /data

STOPSIGNAL SIGTERM
LABEL maintainer="IDI" description="IDI Compiler — CLI + Web"

USER platform

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["generate", "--help"]
