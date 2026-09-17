FROM node:26-alpine

WORKDIR /app

# Sem lockfile no scaffold ainda -> npm install (npm ci exigiria package-lock.json)
COPY package*.json ./
RUN npm install

COPY . .

# Não rodar o dev server como root: usa o usuário `node` (UID 1000) da
# imagem oficial — se o container fosse comprometido, o dano é limitado ao
# app, não ao host (hardening, mesmo padrão do frontend do eval).
RUN chown -R node:node /app
USER node

EXPOSE 5173

CMD ["npm", "run", "dev"]
