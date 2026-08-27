import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getTopics, streamChat } from "./api/client";
import { ChatInput } from "./components/ChatInput";
import { ChatMessage } from "./components/ChatMessage";
import { TopicsSidebar } from "./components/TopicsSidebar";
import type { ChatMessage as ChatMessageType } from "./types";

export default function App() {
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [activeTopic, setActiveTopic] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const streamingIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getTopics()
      .then(setTopics)
      .catch(() => setTopics([]));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, error]);

  const topicCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const topic of topics) {
      counts[topic] = messages.filter(
        (m) => m.role === "assistant" && m.content.toLowerCase().includes(topic.toLowerCase())
      ).length;
    }
    return counts;
  }, [topics, messages]);

  const send = useCallback(
    async (text: string) => {
      const assistantId = crypto.randomUUID();
      const userMessage: ChatMessageType = { id: crypto.randomUUID(), role: "user", content: text };
      const assistantMessage: ChatMessageType = { id: assistantId, role: "assistant", content: "" };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setError(null);
      setStreaming(true);
      streamingIdRef.current = assistantId;

      const controller = new AbortController();
      try {
        await streamChat(
          text,
          sessionId,
          (event) => {
            if (event.type === "token" && typeof event.content === "string") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + event.content } : m
                )
              );
            } else if (event.type === "done") {
              const memoriesUsed = typeof event.memories_used === "number" ? event.memories_used : 0;
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantId ? { ...m, memoriesUsed } : m))
              );
            } else if (event.type === "error") {
              setError(event.detail ?? "Assistente indisponível no momento.");
            }
          },
          controller.signal
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError(err instanceof Error ? err.message : "Não foi possível conectar ao assistente.");
      } finally {
        setStreaming(false);
        streamingIdRef.current = null;
      }
    },
    [sessionId]
  );

  return (
    <div className="flex h-full">
      <TopicsSidebar
        topics={topics}
        counts={topicCounts}
        activeTopic={activeTopic}
        onSelect={setActiveTopic}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
          {messages.length === 0 && (
            <div className="mt-20 text-center">
              <h2 className="text-lg font-semibold text-text-primary">O que estudou hoje?</h2>
              <p className="mt-1 text-sm text-text-secondary">
                Descreva o que aprendeu ou tire uma dúvida — eu guardo tudo por tópico.
              </p>
            </div>
          )}

          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} typing={streaming} />
          ))}

          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <div className="border-t border-border bg-bg/80 p-3 sm:p-4">
          <ChatInput disabled={streaming} onSend={send} />
        </div>
      </main>
    </div>
  );
}