FROM node:22-alpine AS frontend
WORKDIR /build
COPY webfrontend/package.json webfrontend/package-lock.json ./webfrontend/
RUN npm --prefix webfrontend ci
COPY VERSION ./VERSION
COPY webfrontend/index.html webfrontend/vite.config.ts webfrontend/tsconfig.json webfrontend/eslint.config.js ./webfrontend/
COPY webfrontend/src ./webfrontend/src
COPY webfrontend/public ./webfrontend/public
RUN npm --prefix webfrontend run build

FROM python:3.13-slim AS application
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY VERSION ./VERSION
COPY src ./src
COPY webapp ./webapp
COPY prompts ./prompts
COPY --from=frontend /build/webfrontend/dist ./webfrontend/dist
RUN mkdir -p /app/data
EXPOSE 5201
CMD ["python", "-m", "uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "5201", "--no-access-log", "--no-proxy-headers"]
