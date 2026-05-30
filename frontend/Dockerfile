FROM node:22-alpine AS base
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .

FROM base AS dev
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM base AS build
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
