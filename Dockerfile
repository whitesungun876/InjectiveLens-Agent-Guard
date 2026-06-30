# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build

WORKDIR /src/frontend/app
COPY frontend/app/package*.json ./
RUN npm ci
COPY frontend/app/ ./

# The production container serves the API and frontend from the same origin.
ENV VITE_INJECTIVELENS_API_BASE=
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    INJECTIVELENS_STATIC_DIR=/app/frontend-dist \
    INJECTIVELENS_STATE_FILE=/tmp/injectivelens_state.json \
    INJECTIVE_PROOF_RECORDER_MODE=external_tx

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY protocol ./protocol
COPY contracts ./contracts
COPY --from=frontend-build /src/frontend/app/dist ./frontend-dist

EXPOSE 8000

CMD ["sh", "-c", "python -m backend.injectivelens.server --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --quiet"]
