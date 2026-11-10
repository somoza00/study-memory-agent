import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy de dev: no compose aponta para http://backend:8000;
// localmente (sem compose) cai para http://localhost:8001.
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8001";

// Auth da API (`X-API-Key`): quando `API_KEY` está definida, o backend recusa
// toda rota /api sem o header — e em `ENVIRONMENT=production` ele nem sobe sem
// a chave (fail-closed, ver `backend/app/core/config.py`). A UI não mandava o
// header: ligar a autenticação (passo obrigatório para produção) derrubava
// chat, sidebar e buscas com 401 em TODA chamada.
//
// Quem injeta o header é o proxy do dev server, do lado do servidor: a chave
// vem do ambiente do container (o compose passa o mesmo `.env` para backend e
// frontend) e nunca entra no bundle servido ao browser. O prefixo `VITE_` é de
// propósito NÃO usado aqui — variáveis `VITE_*` são embutidas no bundle, o que
// publicaria a API key para qualquer visitante.
const apiKey = process.env.API_KEY;

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
        // Sem `API_KEY` (dev), nada muda: o objeto extra nem existe e o
        // backend continua com a auth desabilitada.
        ...(apiKey ? { headers: { "X-API-Key": apiKey } } : {}),
      },
    },
  },
});
