import { useState } from "react";
import { Navigate } from "react-router";

import { Select } from "../../components/ui/select";
import { ApiError } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { RetencaoHistorico } from "./RetencaoHistorico";
import { NIVEIS_LOG, useSystemSettings, useUpdateLogLevel, type NivelLog } from "./useSystemSettings";

/** Seção de nível de log dos serviços (RF-805): PUT no onChange, sem botão — o valor lido
 *  do GET já é o aplicado nos 4 serviços (convergência ≤ ~10 s pelo watch). */
function NivelLogSection() {
  const settings = useSystemSettings();
  const atualizar = useUpdateLogLevel();
  const [erro, setErro] = useState<string | null>(null);

  if (settings.isPending || settings.isError) return null;

  return (
    <section className="space-y-3 rounded-sm border border-border bg-surface p-4">
      <h2 className="plaqueta text-sm text-fg">Nível de log dos serviços</h2>
      <div className="flex items-center gap-2">
        <Select
          aria-label="Nível de log"
          data-testid="config-log-level"
          className="h-7 w-36 px-2 text-xs"
          value={settings.data.log_level}
          disabled={atualizar.isPending}
          onChange={(evento) => {
            setErro(null);
            atualizar.mutate(evento.target.value as NivelLog, {
              onError: (err) => {
                setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
              },
            });
          }}
        >
          {NIVEIS_LOG.map((nivel) => (
            <option key={nivel} value={nivel}>
              {nivel}
            </option>
          ))}
        </Select>
        {erro && (
          <span role="alert" data-testid="config-log-level-erro" className="text-xs text-alarm">
            {erro}
          </span>
        )}
      </div>
    </section>
  );
}

/** Página de configurações gerais (RF-805): admin-only — operador é redirecionado a `/`
 *  (o item de nav nem é renderizado para ele, AppShell). */
export function SettingsPage() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="font-display text-lg font-bold text-fg">Configurações</h1>
      <RetencaoHistorico />
      <NivelLogSection />
    </div>
  );
}
