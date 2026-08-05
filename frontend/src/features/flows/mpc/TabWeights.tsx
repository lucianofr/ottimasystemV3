import type { VariaveisMpc } from "../graph";
import { formatarNumero } from "../useFlowStatus";
import { rotuloVariavel } from "./mpcLogic";

interface Props {
  variaveis: VariaveisMpc;
}

function LinhaPeso({ id, rotulo, campo, valor }: { id: string; rotulo: string; campo: string; valor: string }) {
  return (
    <div
      data-var-id={id}
      className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-panel border border-hairline bg-well p-2"
    >
      <span className="text-xs text-fg">{rotulo}</span>
      <span className="process-value text-xs text-fg-muted">
        {campo}: {valor}
      </span>
    </div>
  );
}

/**
 * Aba Pesos (spec F4 §7.3): `weight` por CV, `priority` por Restrição — usados na montagem
 * (spec §3.4) para a dominância `w_slack = 10⁴ × max(w_cv) × priority`. Mesma decisão da aba
 * Restrições & Limites: a 4.2 já edita os dois campos na aba Variáveis; esta aba não duplica
 * o `<input>`, só consolida os valores vigentes lado a lado para revisão.
 */
export function TabWeights({ variaveis }: Props) {
  const vazio = variaveis.cvs.length === 0 && variaveis.constraints.length === 0;

  return (
    <div data-testid="mpc-tab-pesos" className="space-y-4">
      <p className="text-xs text-fg-muted">
        Consulta somente leitura — estes campos são editados na aba Variáveis (evita duas
        entradas não-sincronizadas para o mesmo valor).
      </p>

      {vazio && <p className="text-xs text-fg-muted">Nenhuma CV ou Restrição cadastrada.</p>}

      {variaveis.cvs.length > 0 && (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">CVs — peso (w)</h3>
          {variaveis.cvs.map((cv) => (
            <LinhaPeso
              key={cv.id}
              id={cv.id}
              rotulo={rotuloVariavel(cv)}
              campo="peso"
              valor={formatarNumero(cv.weight)}
            />
          ))}
        </div>
      )}

      {variaveis.constraints.length > 0 && (
        <div className="space-y-2">
          <h3 className="plaqueta text-xs text-fg-muted">Restrições — prioridade</h3>
          {variaveis.constraints.map((co) => (
            <LinhaPeso
              key={co.id}
              id={co.id}
              rotulo={rotuloVariavel(co)}
              campo="prioridade"
              valor={String(co.priority)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
