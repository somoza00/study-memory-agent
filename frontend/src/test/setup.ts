// Matchers de DOM do jest-dom (toBeInTheDocument, etc.) para o Vitest.
import "@testing-library/jest-dom/vitest";

// Sem `globals: true` no vitest.config, o auto-cleanup do Testing Library não
// se registra sozinho: sem isto, o DOM de um teste vaza para o próximo e
// queries como getByText encontram elementos duplicados.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
