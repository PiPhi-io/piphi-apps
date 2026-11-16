FROM python:3.12-slim
WORKDIR /app
ENV PDM_CHECK_UPDATE=false PDM_USE_VENV=false
COPY pyproject.toml pdm.lock ./
RUN pip install --no-cache-dir "pdm==2.29.7" \
    && pdm sync --prod --no-self
COPY src ./src
RUN pdm sync --prod --no-editable
EXPOSE 4225
CMD ["pdm", "run", "uvicorn", "piphi_network_reolink.main:app", "--host", "0.0.0.0", "--port", "4225"]
