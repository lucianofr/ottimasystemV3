import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types";

export type AppCertificateOut = components["schemas"]["AppCertificateOut"];
export type AppCertificateGenerateOut = components["schemas"]["AppCertificateGenerateOut"];

export const CHAVE_CERT_APP = ["certificates", "app"] as const;

/**
 * Metadados do certificado de aplicação (spec §6.2-1, tarefa 3.1).
 *
 * `GET /api/certificates/app` é `require_admin` no router inteiro (`certificates.py:25`) —
 * decisão de RBAC do preâmbulo do plano F6b, não reaberta aqui: a query só dispara com
 * `habilitado` verdadeiro (== `useCanMutate()` no chamador). Para o operador ela nunca roda
 * e o 403 nunca chega a existir na tela.
 */
export function useAppCertificate(habilitado: boolean): UseQueryResult<AppCertificateOut> {
  return useQuery({
    queryKey: CHAVE_CERT_APP,
    queryFn: () => api<AppCertificateOut>("/api/certificates/app"),
    enabled: habilitado,
  });
}

/** Gera (ou substitui com `force: true`) o certificado de aplicação (spec §6.2-1). */
export function useGenerateAppCertificate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ force }: { force: boolean }) =>
      api<AppCertificateGenerateOut>("/api/certificates/app/generate", {
        method: "POST",
        body: JSON.stringify({ force }),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE_CERT_APP }),
  });
}
