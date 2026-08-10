import { Card } from "../../components/ui/card";
import { EditorEscala } from "../trend/EditorEscala";
import type { EscalaVar } from "../trend/escalas";
import type { CategoriaVarOperacao, PenaLegenda } from "./trendOperacao";

/**
 * Legenda do trend de operação (spec F5 §7.4-6; plano F5b tarefa 5.3; plano de melhorias
 * Fase 2 tarefa 2.3): checkbox por variável (liga/desliga pena, teto de 8) + editor de
 * escala Y da variável FOCADA (a última ligada na legenda). Só um editor, não um por linha:
 * o trend desenha um único eixo Y visível por vez (`TrendOperacao.tsx`), então editar a
 * escala de uma variável sem eixo desenhado não daria nenhum retorno visual ao operador.
 *
 * Extraído de `TrendOperacao.tsx` para o arquivo caber no teto de 800 linhas (plano, tarefa
 * de teto de arquivo).
 */

/** Mesmos rótulos de `FaceplateVariavel.tsx` (`ROTULO_TIPO`, não exportado de lá — duplicar
 *  um record de 4 linhas é mais barato que acoplar dois arquivos de tarefas diferentes). */
const ROTULO_CATEGORIA: Record<CategoriaVarOperacao, string> = {
  mv: "MV",
  cv: "CV",
  constraint: "Restrição",
  dv: "DV",
};

export interface LegendaOperacaoProps {
  readonly defaults: readonly PenaLegenda[];
  readonly ligadas: ReadonlySet<string>;
  readonly porIdDefinicao: ReadonlyMap<string, { readonly name: string }>;
  readonly cores: ReadonlyMap<string, string>;
  /** Variável focada (dona do único eixo Y visível); `null` quando nenhuma pena está ligada. */
  readonly foco: string | null;
  readonly focoEscala: EscalaVar;
  readonly onAlternarPena: (pena: PenaLegenda) => void;
  readonly onMudarEscalaFoco: (escala: EscalaVar) => void;
}

export function LegendaOperacao({
  defaults,
  ligadas,
  porIdDefinicao,
  cores,
  foco,
  focoEscala,
  onAlternarPena,
  onMudarEscalaFoco,
}: LegendaOperacaoProps) {
  const nomeFoco = foco !== null ? (porIdDefinicao.get(foco)?.name ?? foco) : null;

  return (
    <Card data-testid="operate-trend-legend" className="divide-y divide-border">
      {nomeFoco !== null && (
        <div className="flex flex-wrap items-center justify-between gap-2 bg-surface-2 px-4 py-2.5">
          <span className="plaqueta text-xs text-fg-muted">Escala Y · {nomeFoco}</span>
          <EditorEscala escala={focoEscala} prefixoTestid="operate" aoMudar={onMudarEscalaFoco} />
        </div>
      )}
      {defaults.map((pena) => {
        const definicao = porIdDefinicao.get(pena.id);
        const ligada = ligadas.has(pena.id);
        return (
          <label
            key={pena.id}
            data-testid="operate-trend-legend-item"
            data-var-id={pena.id}
            className="flex cursor-pointer items-center gap-3 px-4 py-2 transition-colors duration-[var(--duration-fast)] hover:bg-surface-2"
          >
            <input
              type="checkbox"
              className="accent-accent"
              checked={ligada}
              onChange={() => {
                onAlternarPena(pena);
              }}
            />
            <span
              aria-hidden="true"
              className="h-1.5 w-6 shrink-0 rounded-pill"
              style={{ backgroundColor: cores.get(pena.id) }}
            />
            <span className="plaqueta grow text-xs">
              {ROTULO_CATEGORIA[pena.categoria]} · {definicao?.name ?? pena.id}
            </span>
            {ligada && pena.id === foco && (
              <span className="plaqueta text-xs text-fg-muted">Eixo Y</span>
            )}
            {pena.excedente && !ligada && (
              <span
                data-testid="operate-trend-legend-teto"
                className="plaqueta rounded-pill bg-warn-soft px-2 py-0.5 text-xs text-warn-fg"
              >
                Acima do teto
              </span>
            )}
          </label>
        );
      })}
    </Card>
  );
}
