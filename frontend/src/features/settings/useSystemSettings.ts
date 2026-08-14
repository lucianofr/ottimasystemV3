import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "../../lib/api";

export const NIVEIS_LOG = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
export type NivelLog = (typeof NIVEIS_LOG)[number];

interface SystemSettingsOut {
  log_level: NivelLog;
}

const CHAVE = ["system-settings"] as const;

/** Nível de log dos 4 serviços (RF-805): GET é `require_operator`; PUT é `require_admin`. */
export function useSystemSettings(): UseQueryResult<SystemSettingsOut> {
  return useQuery({
    queryKey: CHAVE,
    queryFn: () => api<SystemSettingsOut>("/api/system-settings"),
  });
}

/** Persiste e aplica no root logger da API já; os workers convergem em ~10 s (watch). */
export function useUpdateLogLevel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (logLevel: NivelLog) =>
      api<SystemSettingsOut>("/api/system-settings", {
        method: "PUT",
        body: JSON.stringify({ log_level: logLevel }),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: CHAVE }),
  });
}
