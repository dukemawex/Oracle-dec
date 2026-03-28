FROM node:20-alpine AS builder

WORKDIR /app

COPY shared /app/shared
WORKDIR /app/shared
RUN npm ci
RUN npm run build

COPY backend /app/backend
WORKDIR /app/backend
RUN npm ci
RUN npx prisma generate
RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/shared /app/shared
COPY --from=builder /app/backend/package.json /app/backend/package.json
COPY --from=builder /app/backend/package-lock.json /app/backend/package-lock.json

WORKDIR /app/backend
RUN npm ci --omit=dev

COPY --from=builder /app/backend/dist /app/backend/dist
COPY --from=builder /app/backend/prisma /app/backend/prisma
COPY --from=builder /app/backend/node_modules/.prisma /app/backend/node_modules/.prisma

EXPOSE 8080

CMD ["node", "dist/index.js"]
