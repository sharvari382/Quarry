# syntax=docker/dockerfile:1.7
# Builds the React app and bakes it into the nginx image that also load-balances the API.
FROM node:22-alpine AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY sample_data/ /app/sample_data/
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/proxy_common.conf /etc/nginx/proxy_common.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 8080
# nginx runs its workers unprivileged; the master needs no root since we listen on 8080.
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/nginx-health || exit 1
