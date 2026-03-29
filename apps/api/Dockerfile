# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app

# Copy API dependencies and install
COPY package*.json ./apps/api/
WORKDIR /app/apps/api
RUN npm ci

# Copy API source and build
COPY . .
RUN npm run build

# Stage 2: Production runner
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/apps/api/package*.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/apps/api/dist ./dist

# Copy Prisma client if it exists
COPY --from=builder /app/apps/api/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/apps/api/prisma ./prisma

EXPOSE 8080
CMD ["node", "dist/index.js"]
