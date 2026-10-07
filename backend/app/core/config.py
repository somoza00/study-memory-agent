"""Settings via pydantic-settings (Qdrant, OpenAI, Langfuse).

Todos os campos têm defaults de dev para manter o app importável sem
variáveis de ambiente obrigatórias (ex.: testes, CI).
"""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do backend, lida de variáveis de ambiente / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    openai_api_key: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "study_memories"
    agent_model: str = "gpt-4o-mini"
    # Base URL OpenAI-compatível do MODELO DO AGENTE (ex.: OpenCode Zen, Ollama,
    # vLLM, LiteLLM). Vazio = endpoint padrão da OpenAI. Desacopla o projeto de
    # um provedor específico: sem isto, o agente fica preso à OpenAI e o app não
    # roda sem uma chave paga.
    openai_base_url: str | None = None
    # Headers extras do provedor do agente (JSON). Ex.: o OpenCode Go exige um
    # `x-opencode-session` estável para roteamento e cache de prompt.
    openai_extra_headers: dict[str, str] = {}
    # --- Embeddings ---
    # "openai" = endpoint OpenAI-compatível (`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY`);
    # "local"  = ONNX no próprio processo (fastembed), sem chave nem chamada de rede.
    embedding_provider: Literal["openai", "local"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Dimensão do vetor da collection: precisa casar com o modelo escolhido
    # (OpenAI text-embedding-3-small = 1536; MiniLM multilíngue local = 384).
    # Trocar de provedor/dimensão exige recriar a collection (ver README).
    embedding_dim: int = 1536
    # Modelo do provedor local (só usado com EMBEDDING_PROVIDER=local).
    local_embedding_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    # Diretório dos pesos ONNX baixados; None usa o default do fastembed.
    embedding_cache_dir: str | None = None
    # Embeddings têm provedor PRÓPRIO: o endpoint do agente não serve para eles
    # em geral (ex.: o OpenCode Zen/Go expõe só /chat/completions; mandar
    # embedding para lá devolve 404). Vazio = herda `OPENAI_BASE_URL`
    # (compatibilidade com quem aponta os dois para o mesmo servidor
    # self-hosted); para usar a OpenAI só nos embeddings, defina
    # `EMBEDDING_BASE_URL=https://api.openai.com/v1`.
    embedding_base_url: str | None = None
    # Chave do endpoint de embeddings; vazia = usa a mesma do agente.
    embedding_api_key: str = ""
    # Chave de autenticação da própria API (header X-API-Key) para as rotas /api.
    # None = auth desabilitada (dev). Em produção, defina para fechar a API.
    api_key: str | None = None
    environment: str = "development"
    # --- Recall (busca de memória usada no chat) ---
    # Quantas memórias o chat recupera por mensagem.
    recall_limit: int = 5
    # Similaridade mínima para uma memória contar como relevante. Vazio = default
    # por provedor de embedding (ver `recall_score_threshold`): 0.7 para os
    # embeddings da OpenAI, 0.55 para o modelo local. O 0.7 único era calibrado
    # para a OpenAI; medindo com o MiniLM local, consulta não relacionada fica
    # <= 0.19 de score e memória relevante entre 0.62 e 0.89 — metade dos acertos
    # caía fora do corte e o agente respondia sem contexto.
    recall_min_score: float | None = None
    # Escopo do recall do chat (e da tool `recall_memory`):
    #   "all"     = enxerga memórias de TODAS as sessões (default). É o que o
    #               projeto promete — memória persistente entre sessões — e o
    #               frontend cria uma sessão nova a cada carregamento de página;
    #               com escopo por sessão o agente "esquecia" tudo do dia anterior.
    #   "session" = restringe à sessão atual (isolamento por conversa).
    recall_scope: Literal["all", "session"] = "all"
    # Tracing OTel → Langfuse. Desligado por default: sem o Langfuse no ar, o
    # exporter só gera ruído no log e timeout a cada span. Ligue junto com o
    # profile `observability` do compose.
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = "pk-local"
    langfuse_secret_key: str = "sk-local"

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_api_key_means_disabled(cls, value: str | None) -> str | None:
        """`API_KEY=` vazio no .env deve significar "auth desabilitada", não
        uma chave literal de string vazia (que bloquearia toda a API)."""
        return value or None

    @property
    def embedding_key(self) -> str:
        """Chave do endpoint de embeddings (cai para a do agente se não houver)."""
        return self.embedding_api_key or self.openai_api_key

    @property
    def embedding_endpoint(self) -> str | None:
        """Base URL efetiva dos embeddings (`EMBEDDING_BASE_URL` ou herda a do agente)."""
        return self.embedding_base_url or self.openai_base_url

    @field_validator("recall_min_score", mode="before")
    @classmethod
    def _blank_recall_score_means_unset(cls, value: object) -> object:
        """`RECALL_MIN_SCORE=` vazio no `.env` significa "usa o default do provedor"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def recall_score_threshold(self) -> float:
        """Limiar de similaridade efetivo do recall (default depende do provedor)."""
        if self.recall_min_score is not None:
            return self.recall_min_score
        return 0.7 if self.embedding_provider == "openai" else 0.55

    @model_validator(mode="after")
    def _api_key_required_in_production(self) -> Settings:
        """Fail-closed: em produção, subir sem API_KEY é um deploy aberto por
        acidente — melhor o processo nem iniciar do que servir sem auth."""
        if self.environment == "production" and self.api_key is None:
            raise ValueError(
                "environment=production exige API_KEY definida "
                "(auth da API não pode ficar desabilitada em produção)"
            )
        return self


settings = Settings()
