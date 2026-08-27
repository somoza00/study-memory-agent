import type { StreamEvent } from "../types";

const API_BASE = "/api";

export async function getTopics(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/topics`);
  if (!res.ok) return [];
  return (await res.json()) as string[];
}

/**
 * Consome o SSE de `POST /api/chat/stream` via fetch + ReadableStream e
 * chama `onEvent` para cada evento `data:` recebido.
 *
 * Lança `Error` quando a resposta não é 2xx (ex.: 503 de agente
 * indisponível), com a mensagem de `detail` quando disponível.
 */
export async function streamChat(
  message: string,
  sessionId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });

  if (!res.ok) {
    let detail = `Erro do assistente (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // corpo não-JSON; mantém a mensagem padrão
    }
    throw new Error(detail);
  }

  if (!res.body) throw new Error("Stream vazio.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
        if (!dataLine) continue;
        const payload = dataLine.slice(5).trim();
        if (!payload) continue;
        onEvent(JSON.parse(payload) as StreamEvent);
      }
    }
  } finally {
    reader.releaseLock();
  }
}