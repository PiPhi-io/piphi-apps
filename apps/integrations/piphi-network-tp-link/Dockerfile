FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 3666

CMD ["uvicorn", "piphi_network_tp_link.app:app", "--host", "0.0.0.0", "--port", "3666"]
