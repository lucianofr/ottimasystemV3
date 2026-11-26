import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { LabVariableCreate, LabVariableOut } from "./types";

/** Prefixo comum: as análises (`useLabSamples`) moram sob ele, então invalidar a variável
 *  atualiza também a contagem e a tabela. */
export const CHAVE_LAB_VARIAVEIS = ["softsensor", "lab-variables"] as const;

export function useLabVariables(): UseQueryResult<LabVariableOut[]> {
  return useQuery({
    queryKey: CHAVE_LAB_VARIAVEIS,
    queryFn: () => api<LabVariableOut[]>("/api/softsensor/lab-variables"),
  });
}

/** Admin (RBAC no servidor; a tela só mostra o atalho a quem pode mutar). */
export function useCreateLabVariable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LabVariableCreate) =>
      api<LabVariableOut>("/api/softsensor/lab-variables", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHAVE_LAB_VARIAVEIS }),
  });
}
