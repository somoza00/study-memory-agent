import { afterEach, describe, expect, it, vi } from "vitest";

import { getTopicCounts, getTopics, streamChat } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("getTopics", () => {
  it("retorna a lista vinda do backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(["di", "sql"])));
    expect(await getTopics()).toEqual(["di", "sql"]);
  });

  it("degrada para [] quando a resposta não é 2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 500)));
    expect(await getTopics()).toEqual([]);
  });
});

describe("getTopicCounts", () => {
  it("retorna as contagens reais por tópico", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse([{ topic: "di", count: 3 }])),
    );
    expect(await getTopicCounts()).toEqual([{ topic: "di", count: 3 }]);
  });

  it("lança Error em erro do servidor (o chamador decide se tenta de novo)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 503)));

    await expect(getTopicCounts()).rejects.toThrow("(503)");
  });
});

describe("streamChat", () => {
  it("chama onEvent para cada bloco `data:` do SSE", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          'data: {"type":"token","content":"oi"}\n\n',
          'data: {"type":"done","memories_used":1}\n\n',
        ]),
      ),
    );
    const events: unknown[] = [];

    await streamChat("m", "s1", (event) => events.push(event));

    expect(events).toEqual([
      { type: "token", content: "oi" },
      { type: "done", memories_used: 1 },
    ]);
  });

  it("inclui o topic no body quando a sidebar tem tópico ativo", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    vi.stubGlobal("fetch", fetchMock);

    await streamChat("m", "s1", () => {}, undefined, "algebra").catch(() => {});

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      message: "m",
      session_id: "s1",
      topic: "algebra",
    });
  });

  it("omite o topic do body quando não há tópico ativo", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 500));
    vi.stubGlobal("fetch", fetchMock);

    await streamChat("m", "s1", () => {}).catch(() => {});

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ message: "m", session_id: "s1" });
  });

  it("lança Error com o `detail` do backend quando não é 2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "agente indisponível" }, 503)),
    );
    await expect(streamChat("m", "s1", () => {})).rejects.toThrow("agente indisponível");
  });
});
