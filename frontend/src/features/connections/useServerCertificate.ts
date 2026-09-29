import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types";

export type ServerCertificateOut = components["schemas"]["ServerCertificateOut"];
export type ServerCertificatesOut = components["schemas"]["ServerCertificatesOut"];
export type ServerCertificateInfoOut = components["schemas"]["ServerCertificateInfoOut"];

// `useConnections.ts:10` não exporta a chave (mesmo literal já usado sem import em
// `useProjects.ts:28` para a mesma invalidação) — grep confirma o valor real, não inventado.
// A invalidação por prefixo também cobre CHAVE_CERTIFICADO (começa com "connections").
const CHAVE_CONEXOES = ["connections"] as const;
const CHAVE_CERTIFICADO = (id: number) => ["connections", id, "server-certificate"] as const;

/**
 * Estado do certificado do servidor por conexão (RF-202, ADR-021): o que está confiado e o
 * que o servidor ENVIOU — este último capturado pelo opc-worker na falha de pin
 * (`cert_missing`/`cert_mismatch`) e gravado no staging do volume `certs-received`.
 *
 * Poll só em conexão com canal seguro (`segura`): policy `none` nunca tem certificado de
 * servidor para capturar. Enquanto os dois lados estão vazios o poll é de 5 s (a captura
 * depende da próxima tentativa do worker, backoff com teto de 30 s); com algo para
 * mostrar, 30 s basta para perceber rotação sem martelar o endpoint.
 */
export function useServerCertificateInfo(
  id: number,
  segura: boolean,
): UseQueryResult<ServerCertificatesOut> {
  return useQuery({
    queryKey: CHAVE_CERTIFICADO(id),
    queryFn: () => api<ServerCertificatesOut>(`/api/connections/${String(id)}/server-certificate`),
    refetchInterval: (query) => {
      if (!segura) return false;
      const dados = query.state.data;
      if (dados === undefined) return 5000;
      return dados.trusted === null && dados.received === null ? 5000 : 30000;
    },
  });
}

/**
 * Aceite sem upload (spec §6.2-2 revisada): promove o certificado capturado do servidor a
 * confiado — `POST …/server-certificate/trust` com o fingerprint que a UI exibiu. O corpo
 * é a garantia de que o aceite é do certificado INSPECIONADO (ADR-021): se o worker
 * recapturou entre a visualização e o clique, o servidor devolve 409.
 */
export function useTrustReceivedCertificate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fingerprint }: { id: number; fingerprint: string }) =>
      api<ServerCertificateOut>(`/api/connections/${String(id)}/server-certificate/trust`, {
        method: "POST",
        body: JSON.stringify({ fingerprint_sha256: fingerprint }),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_CONEXOES }),
  });
}

/**
 * Deixa de confiar no certificado do servidor (spec §6.2-2). `DELETE`, idempotente —
 * `connections.py` devolve 204 mesmo sem arquivo no disco, então chamar duas vezes
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
