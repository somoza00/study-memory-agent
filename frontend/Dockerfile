FROM node:24-alpine

WORKDIR /app

# Sem lockfile no scaffold ainda -> npm install (npm ci exigiria package-lock.json)
COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
