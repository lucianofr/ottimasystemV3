import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { enviarBinario } from "../../lib/arquivos";
import { fusoDoNavegador } from "./coleta";
import { CHAVE_LAB_VARIAVEIS } from "./useLabVariables";
import type { LabImportOut, LabSampleIn, LabSampleOut } from "./types";

/** Mais recentes 5000 análises da variável, em ordem crescente de coleta (teto do servidor). */
export function useLabSamples(variavelId: number | null): UseQueryResult<LabSampleOut[]> {
  return useQuery({
    queryKey: [...CHAVE_LAB_VARIAVEIS, variavelId, "samples"],
    queryFn: () => api<LabSampleOut[]>(`/api/softsensor/lab-variables/${String(variavelId)}/samples`),
    enabled: variavelId !== null,
  });
}

function useInvalidarVariaveis() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: CHAVE_LAB_VARIAVEIS });
}

/** Operador ou admin; `sampled_at` é o instante da COLETA, em ISO com offset. */
export function useAddLabSample(variavelId: number) {
  const invalidar = useInvalidarVariaveis();
  return useMutation({
    mutationFn: (body: LabSampleIn) =>
      api<LabSampleOut>(`/api/softsensor/lab-variables/${String(variavelId)}/samples`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidar,
  });
}

export function useDeleteLabSample(variavelId: number) {
  const invalidar = useInvalidarVariaveis();
  return useMutation({
    mutationFn: (sampledAt: string) =>
      api<void>(
        `/api/softsensor/lab-variables/${String(variavelId)}/samples?sampled_at=${encodeURIComponent(sampledAt)}`,
        { method: "DELETE" },
      ),
    onSuccess: invalidar,
  });
}

/** CSV cru (`text/csv`, nunca multipart); datas sem fuso valem no fuso do navegador. O arquivo
 *  pode tocar várias variáveis, por isso invalida o prefixo inteiro. */
export function useImportLabSamples() {
  const invalidar = useInvalidarVariaveis();
  return useMutation({
    mutationFn: (arquivo: File) =>
      enviarBinario<LabImportOut>(
        `/api/softsensor/lab-samples/import?tz=${encodeURIComponent(fusoDoNavegador())}`,
        arquivo,
        "text/csv",
      ),
    onSuccess: invalidar,
  });
}
