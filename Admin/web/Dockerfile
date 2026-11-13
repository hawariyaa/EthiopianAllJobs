FROM node:22-alpine
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Where /api requests are forwarded. Next fixes this when it builds, so it is set at build time.
ARG ADMIN_API_URL=http://admin-api:8001
ENV ADMIN_API_URL=$ADMIN_API_URL
RUN npx next build
EXPOSE 3001
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3001"]
