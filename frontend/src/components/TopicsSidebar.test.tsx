import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopicsSidebar } from "./TopicsSidebar";

function renderSidebar(overrides: Partial<Parameters<typeof TopicsSidebar>[0]> = {}) {
  const props = {
    topics: ["fastapi", "react"],
    counts: { fastapi: 3, react: 1 },
    activeTopic: null,
    onSelect: vi.fn(),
    onRename: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
  render(<TopicsSidebar {...props} />);
  return props;
}

describe("TopicsSidebar", () => {
  it("lista os tópicos com a contagem de memórias", () => {
    renderSidebar();

    expect(screen.getByText("fastapi")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("abre o editor ao clicar no lápis e salva com Enter", async () => {
    const onRename = vi.fn().mockResolvedValue(true);
    renderSidebar({ onRename });

    fireEvent.click(screen.getByLabelText("Renomear fastapi"));
    const input = screen.getByLabelText("Novo nome do tópico fastapi") as HTMLInputElement;
    expect(input.value).toBe("fastapi");

    fireEvent.change(input, { target: { value: "FastAPI DI" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onRename).toHaveBeenCalledWith("fastapi", "FastAPI DI"));
    await waitFor(() =>
      expect(screen.queryByLabelText("Novo nome do tópico fastapi")).not.toBeInTheDocument(),
    );
  });

  it("salva pelo botão de confirmar", async () => {
    const onRename = vi.fn().mockResolvedValue(true);
    renderSidebar({ onRename });

    fireEvent.click(screen.getByLabelText("Renomear react"));
    fireEvent.change(screen.getByLabelText("Novo nome do tópico react"), {
      target: { value: "React 19" },
    });
    fireEvent.click(screen.getByLabelText("Salvar novo nome de react"));

    await waitFor(() => expect(onRename).toHaveBeenCalledWith("react", "React 19"));
  });

  it("cancela com Esc sem chamar o backend", () => {
    const onRename = vi.fn().mockResolvedValue(true);
    renderSidebar({ onRename });

    fireEvent.click(screen.getByLabelText("Renomear fastapi"));
    fireEvent.change(screen.getByLabelText("Novo nome do tópico fastapi"), {
      target: { value: "outro nome" },
    });
    fireEvent.keyDown(screen.getByLabelText("Novo nome do tópico fastapi"), { key: "Escape" });

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Novo nome do tópico fastapi")).not.toBeInTheDocument();
  });

  it("não chama o backend quando o nome é igual ou só espaços", () => {
    const onRename = vi.fn().mockResolvedValue(true);
    renderSidebar({ onRename });

    fireEvent.click(screen.getByLabelText("Renomear fastapi"));
    fireEvent.keyDown(screen.getByLabelText("Novo nome do tópico fastapi"), { key: "Enter" });
    expect(onRename).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Renomear fastapi"));
    fireEvent.change(screen.getByLabelText("Novo nome do tópico fastapi"), {
      target: { value: "   " },
    });
    fireEvent.keyDown(screen.getByLabelText("Novo nome do tópico fastapi"), { key: "Enter" });

    expect(onRename).not.toHaveBeenCalled();
  });

  it("mantém o editor aberto quando o backend recusa o nome", async () => {
    const onRename = vi.fn().mockResolvedValue(false);
    renderSidebar({ onRename });

    fireEvent.click(screen.getByLabelText("Renomear fastapi"));
    const input = screen.getByLabelText("Novo nome do tópico fastapi");
    fireEvent.change(input, { target: { value: "react" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(onRename).toHaveBeenCalledWith("fastapi", "react"));
    // O texto digitado continua ali para o usuário corrigir.
    expect((input as HTMLInputElement).value).toBe("react");
  });

  it("seleciona o tópico ao clicar no item (fora do modo edição)", () => {
    const onSelect = vi.fn();
    renderSidebar({ onSelect });

    fireEvent.click(screen.getByText("fastapi"));

    expect(onSelect).toHaveBeenCalledWith("fastapi");
  });
});
