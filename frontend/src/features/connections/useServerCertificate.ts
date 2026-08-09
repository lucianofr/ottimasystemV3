import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { enviarBinario } from "../../lib/arquivos";

export type ServerCertificateOut = components["schemas"]["ServerCertificateOut"];

/**
 * Content-Type do upload de trust (spec §6.0-2; `connections.py:250-263` documenta que o
 * backend aceita `application/octet-stream`, `application/x-pem-file` ou `application/pkix-cert`
 * sem conferir o header — `_ler_certificado` só lê o corpo bruto em stream. Escolhido
 * `application/octet-stream`: o arquivo do roteiro E2E (B-F6-04, `opcsim.der`) e o exportado
 * pela chapa de certificado da aplicação (tarefa 3.1) são DER binário, não o texto base64 de
 * um `.pem` — o tipo genérico de binário é o correto para o formato que a tela realmente
 * envia, e como o servidor não valida o header, os três valores são funcionalmente idênticos.
 */
export const TIPO_CERTIFICADO_SERVIDOR = "application/octet-stream";

/** Teto espelhado do cliente (spec §6.2-3, `connections.py:42`, `MAX_SERVER_CERT_BYTES`).
 *  Só evita um round-trip óbvio antes de enviar — o servidor continua sendo a barreira real
 *  (413, `_ler_certificado`), este valor nunca substitui aquela checagem. */
export const MAX_SERVER_CERT_BYTES = 64 * 1024;

/** Pura: diz se um arquivo já recusaria no servidor antes de gastar a requisição. */
export function certificadoExcedeLimite(tamanhoBytes: number): boolean {
  return tamanhoBytes > MAX_SERVER_CERT_BYTES;
}

// `useConnections.ts:14` não exporta a chave (mesmo literal já usado sem import em
// `useProjects.ts:28` para a mesma invalidação) — grep confirma o valor real, não inventado.
const CHAVE_CONEXOES = ["connections"] as const;

/**
 * Confia no certificado do servidor por conexão (spec §6.2-2, RF-202, ADR-021, tarefa 3.2).
 *
 * Upload binário cru via `enviarBinario` — nunca em formulário multipart: o endpoint lê o
 * corpo em stream (`connections.py:106-126`) e um upload de formulário quebraria essa
 * leitura. Devolve o `ServerCertificateOut` com o `fingerprint_sha256` do que foi de fato
 * gravado no disco (não do que chegou), para o admin conferir contra o servidor.
 */
export function useTrustServerCertificate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, arquivo }: { id: number; arquivo: File }) =>
      enviarBinario<ServerCertificateOut>(
        `/api/connections/${String(id)}/server-certificate`,
        arquivo,
        TIPO_CERTIFICADO_SERVIDOR,
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_CONEXOES }),
  });
}

/**
 * Deixa de confiar no certificado do servidor (spec §6.2-2). `DELETE`, idempotente —
 * `connections.py:301-308` devolve 204 mesmo sem arquivo no disco, então chamar duas vezes
 * nunca quebra a tela.
 */
export function useClearServerCertificate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<void>(`/api/connections/${String(id)}/server-certificate`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_CONEXOES }),
  });
}
