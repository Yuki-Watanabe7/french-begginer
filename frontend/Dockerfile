# ベースイメージは版と digest で固定する。更新手順は docs/operations/local-lan-runbook.md。
FROM node:22.23.4-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

FROM base AS dev
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM base AS build
# 本番は nginx と同一オリジンの /api を呼ぶ。別オリジンの API や localhost を埋め込まない
ENV VITE_API_BASE=
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03 AS prod
# 入口では curl を使わない（healthcheck は busybox wget）。攻撃面と既知 CVE を減らす
USER root
RUN apk del --no-cache curl
USER 101
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
