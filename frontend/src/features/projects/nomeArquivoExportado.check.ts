import { expect, test } from "@playwright/test";

import { nomeArquivoExportado } from "./nomeArquivoExportado";

/**
 * Casos espelham byte a byte os testes do backend para `_slug`
 * (`services/api/tests/test_projects_export.py:123-180`) — mesmo nome de projeto, mesmo
 * filename esperado, para o fallback client-side nunca divergir do `Content-Disposition` real.
 */

test("nome simples vira slug minúsculo com extensão .ottima.json", () => {
  expect(nomeArquivoExportado("Planta C-101")).toBe("planta-c-101.ottima.json");
});

test("símbolos que reduzem a vazio caem em projeto.ottima.json", () => {
  expect(nomeArquivoExportado("!!!???")).toBe("projeto.ottima.json");
});

test("acentos e barras colapsam num único hífen, sem hífen nas pontas", () => {
  expect(nomeArquivoExportado("Café / Preto //")).toBe("caf-preto.ottima.json");
});
