# MotionSim in a container: the page, the engine, the datasheet reader, the local store.
#
#   docker compose up            then open http://127.0.0.1:4310/ (a coding agent: /mcp, docs/MCP.md)
#
# Two stages: the first builds the package and everything it needs into one folder, the
# second is a slim image with that folder and nothing that built it. The page itself is
# already built and in the source tree (src/motionsim/webui), so no Node is needed.

# The base is named by its digest, so that the image is built from the same bytes until the
# digest is changed here on purpose: python:3.12-slim as it was when last brought up to date.
FROM docker.io/library/python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/motionsim
WORKDIR /src
# What the package is built from, and no more: see pyproject.toml.
COPY pyproject.toml README.md LICENSE DISCLAIMER.md THIRD_PARTY.md ./
COPY src ./src
COPY examples ./examples
# The page on FastAPI and uvicorn, and the libraries that read a datasheet PDF.
# pip goes once it has installed them: nothing installs anything in the running image.
RUN /opt/motionsim/bin/pip install --no-cache-dir ".[app,reader]" \
    && /opt/motionsim/bin/pip uninstall --yes pip


# python:3.12-slim, the same digest as above.
FROM docker.io/library/python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

LABEL org.opencontainers.image.title="MotionSim" \
      org.opencontainers.image.description="Compare power transistors against your own motor and load: the local page" \
      org.opencontainers.image.licenses="Apache-2.0"

# Nothing in here runs as root. /data is MotionSim's folder: the device files, the store and
# the reader's key, kept in a volume so that they outlast the container, with the figures
# the engine keeps so as not to work them out twice.
# gcc and the C library's headers: the C export's replay compiles the law here and runs it
# against the engine, and a port to a microcontroller is written only on a law it passed.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 motionsim \
    && mkdir --mode=0700 /data \
    && chown motionsim:motionsim /data \
    && python -m pip uninstall --yes --no-cache-dir --root-user-action=ignore pip
COPY --from=build /opt/motionsim /opt/motionsim
# The user's guide and the agent's, which the MCP server at /mcp offers an agent to read.
COPY docs/GUIDE.md docs/MCP.md /opt/motionsim/share/motionsim/docs/

ENV PATH="/opt/motionsim/bin:$PATH" \
    MOTIONSIM_HOME=/data \
    MOTIONSIM_CACHE=/data/cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# The address the page is opened at from outside, as host:port: the port inside is not the one
# the host publishes, and the interfaces inside are not the ones others reach. Set by
# docker-compose.yml; where it is not set, the page says the address inside and that every
# interface of the container is answered.
ENV MOTIONSIM_PUBLISHED=""
USER motionsim
WORKDIR /home/motionsim
VOLUME /data
EXPOSE 8000

# The page's own address inside the container: answered once the engine is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/engine/mode.json', timeout=4)"]

# Every interface of the container, which is reached only through the port the host
# publishes: docker-compose.yml publishes it on 127.0.0.1 alone.
CMD ["motionsim", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
