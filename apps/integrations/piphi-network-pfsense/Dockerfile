FROM node:22-slim AS widgets
WORKDIR /widgets
COPY widgets ./
RUN for widget in pfsense-overview pfsense-client-security; do \
      cd "/widgets/$widget" && npm ci --ignore-scripts && npm run build || exit 1; \
    done

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=widgets /widgets ./widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/data/piphi/automation-actions.sqlite3
ENV PIPHI_WIDGET_DIR=/app/widgets
VOLUME ["/data/piphi"]
EXPOSE 8090
CMD ["uvicorn", "piphi_network_pfsense.main:app", "--host", "0.0.0.0", "--port", "8090"]
