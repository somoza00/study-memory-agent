import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import App from "./App";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeAll(() => {
  // jsdom não implementa scrollIntoView, e o App rola a lista ao montar.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App — sidebar de tópicos", () => {
  it("tenta de novo e mostra os tópicos quando a primeira chamada falha", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        calls += 1;
        return Promise.resolve(
          calls === 1
            ? jsonResponse({}, 503) // backend ainda subindo
            : jsonResponse([{ topic: "fastapi", count: 2 }]),
        );
      }),
    );

    render(<App />);

    await waitFor(() => expect(screen.getByText("fastapi")).toBeInTheDocument(), {
      timeout: 4000,
    });
    expect(calls).toBeGreaterThan(1);
  });

  it("explica a sidebar vazia quando todas as tentativas falham", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 503)));

    render(<App />);

    await waitFor(
      () => expect(screen.getByText(/Não foi possível carregar os tópicos/)).toBeInTheDocument(),
      { timeout: 8000 },
    );
    expect(screen.getByText("Nenhum tópico ainda.")).toBeInTheDocument();
  });
});
