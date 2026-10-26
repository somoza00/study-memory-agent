FROM node:26-alpine

WORKDIR /app

# `npm ci` (não `npm install`): o package-lock.json está commitado e é o que
# o CI e o `make frontend-build` usam. Com `npm install`, a imagem podia
# resolver versões diferentes das que o CI testou — ou reescrever o lock
# dentro do build — então o container subia com uma árvore de deps que
# nenhum gate viu. O comentário anterior ("sem lockfile no scaffold") ficou
# obsoleto quando o lock foi commitado.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Não rodar o dev server como root: usa o usuário `node` (UID 1000) da
# imagem oficial — se o container fosse comprometido, o dano é limitado ao
# app, não ao host (hardening, mesmo padrão do frontend do eval).
RUN chown -R node:node /app
USER node

EXPOSE 5173

CMD ["npm", "run", "dev"]
