FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --upgrade pip

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install .

EXPOSE 3671

CMD ["python", "-m", "piphi_network_aqara.app"]
