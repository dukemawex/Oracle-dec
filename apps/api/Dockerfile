FROM node:20-alpine AS builder

WORKDIR /app

COPY packages/shared /app/packages/shared
WORKDIR /app/packages/shared
RUN npm ci
RUN npm run build

COPY apps/api /app/apps/api
WORKDIR /app/apps/api
RUN npm ci
RUN npx prisma generate
RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/packages/shared /app/packages/shared
COPY --from=builder /app/apps/api/package.json /app/apps/api/package.json
COPY --from=builder /app/apps/api/package-lock.json /app/apps/api/package-lock.json

WORKDIR /app/apps/api
RUN npm ci --omit=dev

COPY --from=builder /app/apps/api/dist /app/apps/api/dist
COPY --from=builder /app/apps/api/prisma /app/apps/api/prisma
COPY --from=builder /app/apps/api/node_modules/.prisma /app/apps/api/node_modules/.prisma

EXPOSE 8080

CMD ["node", "dist/index.js"]
