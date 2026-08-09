import { expect, test } from "@playwright/test";

import { certificadoExcedeLimite, MAX_SERVER_CERT_BYTES } from "./useServerCertificate";

/**
 * `certificadoExcedeLimite` — tarefa 3.2 do plano F6b (spec §6.2-3, `connections.py:42`).
 * Espelha o teto do servidor (`MAX_SERVER_CERT_BYTES = 64 * 1024`) no cliente, só para avisar
 * antes de gastar a requisição — a barreira real continua sendo o 413 do backend.
 */
test("teto confere com o backend (65536 bytes)", () => {
  expect(MAX_SERVER_CERT_BYTES).toBe(65536);
});

test("exatamente no teto não excede (limite é inclusivo, igual ao backend)", () => {
  expect(certificadoExcedeLimite(MAX_SERVER_CERT_BYTES)).toBe(false);
});

test("um byte acima do teto excede", () => {
  expect(certificadoExcedeLimite(MAX_SERVER_CERT_BYTES + 1)).toBe(true);
});

test("arquivo pequeno não excede", () => {
  expect(certificadoExcedeLimite(1024)).toBe(false);
});

test("arquivo vazio não excede", () => {
  expect(certificadoExcedeLimite(0)).toBe(false);
});
