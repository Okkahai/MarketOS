FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 marketos && adduser -S -u 10001 -G marketos marketos
COPY --from=build --chown=marketos:marketos /app/.next/standalone ./
COPY --from=build --chown=marketos:marketos /app/.next/static ./.next/static
USER marketos
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]
