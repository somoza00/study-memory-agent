import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TypingIndicator } from "./TypingIndicator";

describe("TypingIndicator", () => {
  it("mostra três pontos animados", () => {
    const { container } = render(<TypingIndicator />);

    expect(container.querySelectorAll("span")).toHaveLength(3);
  });

  it("aplica delays escalonados na animação", () => {
    const { container } = render(<TypingIndicator />);

    const delays = Array.from(container.querySelectorAll("span")).map(
      (dot) => (dot as HTMLElement).style.animationDelay,
    );
    expect(delays).toEqual(["0ms", "150ms", "300ms"]);
    expect(container.firstChild).toBeInTheDocument();
  });
});
