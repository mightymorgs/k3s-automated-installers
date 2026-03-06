# Stage 1: Download CLI binaries
FROM debian:bookworm-slim AS binaries

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip

# bws CLI (Bitwarden Secrets Manager)
ARG BWS_VERSION=1.0.0
RUN DPKG_ARCH=$(dpkg --print-architecture) && \
    case "$DPKG_ARCH" in arm64) ARCH=aarch64;; amd64) ARCH=x86_64;; *) ARCH=$DPKG_ARCH;; esac && \
    curl -fsSL "https://github.com/bitwarden/sdk-sm/releases/download/bws-v${BWS_VERSION}/bws-${ARCH}-unknown-linux-gnu-${BWS_VERSION}.zip" \
    -o /tmp/bws.zip && \
    unzip /tmp/bws.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/bws

# gh CLI (GitHub CLI)
ARG GH_VERSION=2.63.2
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.tar.gz" \
    | tar xz -C /tmp && \
    mv /tmp/gh_${GH_VERSION}_linux_${ARCH}/bin/gh /usr/local/bin/gh && \
    chmod +x /usr/local/bin/gh

# Stage 2: Build React SPA
FROM node:20-slim AS frontend

WORKDIR /build
COPY vm-builder/vm-builder-web/package.json vm-builder/vm-builder-web/package-lock.json* ./
RUN npm ci
COPY vm-builder/vm-builder-web/ ./
RUN npm run build

# Stage 3: Runtime
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    git \
    && rm -rf /var/lib/apt/lists/*

# CLI binaries from stage 1
COPY --from=binaries /usr/local/bin/bws /usr/local/bin/bws
COPY --from=binaries /usr/local/bin/gh /usr/local/bin/gh

# Non-root user
RUN useradd -r -m -s /bin/bash platform

WORKDIR /app
COPY pyproject.toml /app/
COPY idi/ /app/idi/
COPY vm-builder/vm_builder/ /app/vm_builder/
COPY vm-builder/vm-builder-web/ /app/web/
COPY --from=frontend /build/dist /app/web/dist

# Install package (includes vm-builder CLI entrypoint)
RUN pip install --no-cache-dir /app

# Entrypoint wrapper script
RUN printf '#!/bin/bash\ncase "$1" in\n  web)\n    shift\n    exec uvicorn vm_builder.api.app:app --host 0.0.0.0 --port 8080 "$@"\n    ;;\n  *)\n    exec vm-builder "$@"\n    ;;\nesac\n' > /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

RUN mkdir -p /output /config /data/reference /data \
    && chown -R platform:platform /output /config /data

STOPSIGNAL SIGTERM
LABEL maintainer="IDI" description="VM Builder CLI + Web UI"

USER platform

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]

