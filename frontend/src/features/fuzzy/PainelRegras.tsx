import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { tresCasas } from "./fuzzyMath";
import type { FuzzyRuleBlockOut } from "./types";

/**
 * Tabela de regras da FUZZY OPERATE (ADR-030) — regras achatadas de `rule_blocks` na mesma
 * ordem de `FuzzyState.rules` (o servidor garante o alinhamento, `introspect.py`), grau de
 * ativação com barra proporcional.
 *
 * O destaque verde marca a regra DOMINANTE (maior grau), não toda regra com grau > 0: termos
 * de pertinência global (`Bell`, `Sigmoid` — o FLL padrão usa Bell) ativam TODAS as regras em
 * algum grau a cada execução, então "grau > 0" pintaria a tabela inteira e esconderia
 * justamente a informação pedida — qual regra está mandando na inferência agora.
 */

export interface PainelRegrasProps {
  readonly ruleBlocks: readonly FuzzyRuleBlockOut[];
  /** `FuzzyState.rules` — `undefined` antes da primeira execução (cold-start, todo grau 0). */
  readonly graus: readonly number[] | undefined;
}

export function PainelRegras({ ruleBlocks, graus }: PainelRegrasProps) {
  const regras = ruleBlocks.flatMap((bloco) => bloco.rules);
  const ativas = regras.filter((_regra, indice) => (graus?.[indice] ?? 0) > 0).length;
  const indiceDominante = regras.reduce(
    (melhor, _regra, indice) =>
      (graus?.[indice] ?? 0) > (graus?.[melhor] ?? 0) ? indice : melhor,
    0,
  );

  return (
    <Card className="p-4" data-testid="fuzzy-painel-regras">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">Regras</h3>
        <Badge tone={ativas > 0 ? "success" : "neutral"} data-testid="fuzzy-regras-ativas">
          {ativas}/{regras.length} ativas
        </Badge>
      </div>
      <table className="mt-3 w-full text-left text-xs">
        <thead>
          <tr className="text-fg-muted">
            <th className="w-8 pb-1 font-medium">#</th>
            <th className="pb-1 font-medium">Regra</th>
            <th className="w-32 pb-1 text-right font-medium">Grau</th>
          </tr>
        </thead>
        <tbody>
          {regras.map((texto, indice) => {
            const grau = graus?.[indice] ?? 0;
            const ativa = grau > 0;
            const dominante = ativa && indice === indiceDominante;
            return (
              <tr
                key={`${String(indice)}-${texto}`}
                data-testid="fuzzy-regra-linha"
                data-ativa={ativa ? "true" : "false"}
                data-dominante={dominante ? "true" : "false"}
                className={cn("border-t border-border", dominante && "bg-success-soft")}
              >
                <td className="py-1.5 text-fg-muted">{indice + 1}</td>
                <td className="py-1.5">{texto}</td>
                <td className="py-1.5">
                  <div className="flex items-center justify-end gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-pill bg-well">
                      <div
                        className="h-full bg-accent transition-all duration-[var(--duration-base)] ease-[var(--ease-out)]"
                        style={{ width: `${String(Math.min(100, Math.max(0, grau * 100)))}%` }}
                      />
                    </div>
                    <span className="process-value w-10 text-right">{tresCasas(grau)}</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
