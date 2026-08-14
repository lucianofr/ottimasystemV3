import type { VariaveisMpc } from "../graph";
import { formatarNumero } from "../useFlowStatus";
import { rotuloVariavel } from "./mpcLogic";

interface Props {
  variaveis: VariaveisMpc;
}

function LinhaResumo({ id, rotulo, colunas }: { id: string; rotulo: string; colunas: [string, string][] }) {
  return (
    <div
      data-var-id={id}
      className="grid grid-cols-[1fr_repeat(4,auto)] items-center gap-3 rounded-sm border border-border bg-well p-2"
    >
      <span className="text-xs text-fg">{rotulo}</span>
      {colunas.map(([campo, valor]) => (
        <span key={campo} className="process-value text-xs text-fg-muted" title={campo}>
          {campo}: {valor}
        </span>
      ))}
    </div>
  );
}

/**
 * Aba Restrições & Limites (spec F4 §7.3): `limits`/`max_rate`/`initial_value` (MV),
 * `sp_limits` (CV) e `range` (Restrição) — a 4.2 já colocou todos esses campos como entrada
 * editável na aba Variáveis (um fieldset por variável, identidade + números juntos). Duplicar
 * os mesmos `<input name=...>` aqui criaria dois campos não-sincronizados editando o mesmo
 * valor (o brief pede exatamente para evitar isso). Esta aba cobre o que a Variáveis não
 * cobre: uma leitura consolidada por categoria, útil para revisar os limites de todas as
 * variáveis de uma vez sem paginar fieldset por fieldset — sem estado próprio, lê direto de
 * `variaveis`.
 */
export function TabLimits({ variaveis }: Props) {
  const vazio =
    variaveis.mvs.length === 0 && variaveis.cvs.length === 0 && variaveis.constraints.length === 0;

  return (
    <div data-testid="mpc-tab-restricoes-limites" className="space-y-4">
      <p className="text-xs text-fg-muted">
        Consulta somente leitura — estes campos são editados na aba Variáveis (evita duas
        entradas não-sincronizadas para o mesmo valor).
      </p>

      {vazio && <p className="text-xs text-fg-muted">Nenhuma MV, CV ou Restrição cadastrada.</p>}

      {variaveis.mvs.length > 0 && (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">MVs — limites e Δu</h3>
          {variaveis.mvs.map((mv) => (
            <LinhaResumo
              key={mv.id}
              id={mv.id}
              rotulo={rotuloVariavel(mv)}
              colunas={[
                ["mín.", formatarNumero(mv.limits.min)],
                ["máx.", formatarNumero(mv.limits.max)],
                ["taxa máx. (EU/s)", formatarNumero(mv.max_rate)],
                ["inicial", formatarNumero(mv.initial_value)],
              ]}
            />
          ))}
        </div>
      )}

      {variaveis.cvs.length > 0 && (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">CVs — faixa de SP</h3>
          {variaveis.cvs.map((cv) => (
            <LinhaResumo
              key={cv.id}
              id={cv.id}
              rotulo={rotuloVariavel(cv)}
              colunas={[
                ["SP mín.", formatarNumero(cv.sp_limits.min)],
                ["SP máx.", formatarNumero(cv.sp_limits.max)],
              ]}
            />
          ))}
        </div>
      )}

      {variaveis.constraints.length > 0 && (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">Restrições — faixa</h3>
          {variaveis.constraints.map((co) => (
            <LinhaResumo
              key={co.id}
              id={co.id}
              rotulo={rotuloVariavel(co)}
              colunas={[
                ["mín.", formatarNumero(co.range.low)],
                ["máx.", formatarNumero(co.range.high)],
              ]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
