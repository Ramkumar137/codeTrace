FROM python:3.12.8-slim

RUN pip install --no-cache-dir nbclient==0.10.2 ipykernel==6.29.5 nbformat==5.10.4 \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin codetrace

COPY runner.py /opt/codetrace/runner.py
USER 10001:10001
WORKDIR /workspace
ENV HOME=/tmp \
    JUPYTER_RUNTIME_DIR=/tmp \
    PYTHONDONTWRITEBYTECODE=1
