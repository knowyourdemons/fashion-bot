FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --production

COPY server.mjs ./
COPY fonts/ ./fonts/
COPY emoji/ ./emoji/

EXPOSE 3100

CMD ["node", "server.mjs"]
