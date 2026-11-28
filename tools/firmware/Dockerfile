# MotionSim's firmware service: the cross-compilers a port to a microcontroller is compiled with,
# and nothing else. Optional; started with
#
#   docker compose --profile firmware up
#
# It runs src/motionsim/control/codegen/firmware.py, which compiles each source to an object and
# says whether it compiled, its warnings and its size. Nothing is linked and nothing is run.
#
# Carried: arm-none-eabi-gcc with newlib (the Cortex-M chips), riscv64-unknown-elf-gcc with
# picolibc (a RISC-V chip typed in), and the ESP32-S3's xtensa-esp32s3-elf-gcc, fetched from its
# makers' release by a fixed checksum. Not carried, so source only: the C2000 compiler (cl2000)
# and XC16, which may not be redistributed.

# python:3.12-slim, the same digest as the main image (Dockerfile).
FROM docker.io/library/python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG XTENSA=xtensa-esp32s3-elf-12.2.0_20230208-x86_64-linux-gnu.tar.xz
ARG XTENSA_SHA256=29b5ea6b30d98231f0c17f2327404109e0abf59b48d0f2890d9d9899678a89a3
ARG XTENSA_URL=https://github.com/espressif/crosstool-NG/releases/download/esp-12.2.0_20230208

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        gcc-arm-none-eabi libnewlib-arm-none-eabi binutils-arm-none-eabi \
        gcc-riscv64-unknown-elf picolibc-riscv64-unknown-elf \
        ca-certificates curl xz-utils \
    && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl --fail --location --silent --show-error --output /tmp/xtensa.tar.xz "$XTENSA_URL/$XTENSA" \
        && echo "$XTENSA_SHA256  /tmp/xtensa.tar.xz" | sha256sum --check - \
        && tar --extract --file /tmp/xtensa.tar.xz --directory /opt \
        && rm /tmp/xtensa.tar.xz; \
    fi \
    && apt-get purge --yes curl xz-utils \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 firmware

ENV PATH="/opt/xtensa-esp32s3-elf/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY src/motionsim/control/codegen/firmware.py /srv/firmware.py
USER firmware
WORKDIR /home/firmware
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8090/health', timeout=4)"]
# Every interface of the container, which is reached only through the port compose publishes
# (127.0.0.1 alone) and by the page's container on compose's own network. Outside a container
# the service listens on 127.0.0.1. Each request carries MOTIONSIM_FIRMWARE_TOKEN, which compose
# hands this service and the page alike (make firmware-token).
CMD ["python", "/srv/firmware.py", "--serve", "8090", "--host", "0.0.0.0"]
