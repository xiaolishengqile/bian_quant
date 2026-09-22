FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home quant
COPY backend/ ./backend/
COPY --from=web /web/dist/ ./frontend/dist/
RUN mkdir -p /app/data && chown -R quant:quant /app
USER quant
EXPOSE 8765
CMD ["python", "-m", "backend", "--host", "0.0.0.0"]
