// Contratos de domínio do frontend (espelham os schemas do backend).
// TODO: manter em sincronia com backend/app/models.

export interface Memory {
  id: string;
  text: string;
  topic: string;
  source: string;
  date: string;
  session_id: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
