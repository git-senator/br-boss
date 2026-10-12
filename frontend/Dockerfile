FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# ci, e não install: as versões vêm do package-lock.json, então o build
# no servidor do cliente gera exatamente o mesmo que aqui.
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# Imagem final: só o app compilado, sem código-fonte e sem
# ferramentas de build. Assim ela fica menor e é transferida mais rápido.
FROM node:22-alpine AS runtime
WORKDIR /app
# tzdata: sem ele o Alpine não conhece fusos horários e TZ não muda nada —
# «hoje» e «ontem» na lista de e-mails seriam calculados pelo horário de Greenwich.
RUN apk add --no-cache tzdata
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

# node:alpine já tem o usuário node com uid 1000 — rodamos com ele.
RUN chown -R node:node /app
USER node

EXPOSE 3000
CMD ["node", "server.js"]
