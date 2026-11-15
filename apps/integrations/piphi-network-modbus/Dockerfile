FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /app
RUN pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
RUN addgroup --system --gid 10001 piphi \
    && adduser --system --uid 10001 --ingroup piphi --home /app piphi \
    && mkdir -p /app/data \
    && chown -R piphi:piphi /app
USER 10001:10001
EXPOSE 4222
CMD ["uvicorn", "piphi_network_modbus.main:app", "--host", "0.0.0.0", "--port", "4222"]
