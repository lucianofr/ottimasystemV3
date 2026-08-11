import { Card } from "../../components/ui/card";
import type { MpcState } from "../../lib/contracts.gen";
import { formatarNumero } from "../flows/useFlowStatus";
import { ROTULO_STATUS_SSTO, resumoOtimizador } from "./resumoOtimizador";
import type { MpcNodeOut } from "./useMpcs";
import { useUltimoSsto } from "./useUltimoSsto";

/**
 * Sumário do otimizador (ADR-027 §9 estendido) — card logo abaixo do `FaceplatePrincipal`:
 * badge de status da última execução do SSTO, valor da função objetivo e, por variável
 * otimizada, o valor ATUAL (canal ao vivo) e o ALVO calculado (`mv_target`/`cv_target`).
 *
 * Ausente quando nenhuma variável tem `objective !== "none"` (o card não existe — não um
 * card vazio); com variável otimizada mas sem nenhuma execução ainda, mostra o estado
 * "aguardando" em vez de inventar números. Fonte de dado: `mpcState.ssto` (WS, com
 * carry-forward do `reduzir`) precedendo o cold-start REST (`useUltimoSsto`).
 */

const COR_STATUS: Record<string, string> = {
  optimal: "bg-success-soft text-success-fg",
  relaxed: "bg-warn-soft text-warn-fg",
  infeasible: "bg-alarm-soft text-alarm",
  unbounded: "bg-alarm-soft text-alarm",
  error: "bg-alarm-soft text-alarm",
};

function formatar(valor: number | null): string {
  return valor === null ? "—" : formatarNumero(valor);
}

export function ResumoOtimizador({
  mpc,
  mpcState,
  flowId,
  blockId,
}: {
  mpc: MpcNodeOut;
  mpcState: MpcState | undefined;
  flowId: number;
  blockId: string;
}) {
  const ultimo = useUltimoSsto(flowId, blockId);
  const { ssto, linhas, desistencias } = resumoOtimizador(
    mpc,
    mpcState,
    ultimo.data?.run ?? null,
  );

  // Nenhuma variável otimizada: o card simplesmente não existe (a tela fica exatamente
  // como antes da feature — decisão de não poluir bloco sem economia configurada).
  if (linhas.length === 0) return null;

  return (
    <Card className="p-4" data-testid="resumo-otimizador">
      <div className="mb-3 flex items-center justify-between gap-4">
        <span className="plaqueta text-xs text-fg-muted">Otimizador</span>
        {ssto !== null && (
          <div className="flex items-center gap-3">
            <span
              data-testid="resumo-otimizador-status"
              className={`inline-flex items-center rounded-pill px-2.5 py-1 text-[11px] ${COR_STATUS[ssto.status]}`}
            >
              {ROTULO_STATUS_SSTO[ssto.status]}
            </span>
            <span className="plaqueta text-[10px] text-fg-muted">
              Objetivo{" "}
              <span className="process-value" data-testid="resumo-otimizador-objetivo">
                {formatarNumero(ssto.objective)}
              </span>
            </span>
          </div>
        )}
      </div>

      {ssto === null ? (
        <p className="text-sm text-fg-muted">Aguardando primeira execução do otimizador</p>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="plaqueta text-left text-[10px] text-fg-muted">
                <th className="pb-1 font-normal">Variável</th>
                <th className="pb-1 font-normal">Objetivo</th>
                <th className="pb-1 text-right font-normal">Atual</th>
                <th className="pb-1 text-right font-normal">Alvo</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((linha) => (
                <tr key={linha.id} className="border-t border-border/50">
                  <td className="py-1.5 pr-2">
                    <span className="text-fg">{linha.nome}</span>{" "}
                    <span className="text-[10px] text-fg-muted">{linha.eu}</span>
                  </td>
                  <td className="py-1.5 pr-2 text-fg-muted">{linha.rotuloObjetivo}</td>
                  <td className="process-value py-1.5 pr-2 text-right">
                    {formatar(linha.atual)}
                  </td>
                  <td className="process-value py-1.5 text-right">{formatar(linha.alvo)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {desistencias.length > 0 && (
            <p className="mt-2 text-[11px] text-warn-fg">
              O otimizador desistiu de: {desistencias.join(", ")}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
