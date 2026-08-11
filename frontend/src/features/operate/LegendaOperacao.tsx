import { Card } from "../../components/ui/card";
import { EditorEscala } from "../trend/EditorEscala";
import { ESCALA_AUTO, type EscalaVar } from "../trend/escalas";
import type { CategoriaVarOperacao, PenaLegenda } from "./trendOperacao";

/**
 * Legenda do trend de operação (spec F5 §7.4-6; plano F5b tarefa 5.3; plano de melhorias
 * Fase 2 tarefa 2.3): uma linha por variável, com o checkbox que liga/desliga a pena (teto
 * de 8) e o editor de escala Y (mín/máx + AUTOSCALE) na PRÓPRIA linha — mesmo arranjo da
 * legenda do trend de engenharia (`TrendPage.tsx`).
 *
 * Cada variável tem escala uPlot própria (`construirEscalasUplot`), então fixar a faixa de
 * uma pena move só aquela pena no gráfico. O eixo Y desenhado é outra coisa: só a variável
 * focada ganha eixo visível, e isso não restringe de quem a faixa pode ser editada.
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
  /** Escala Y de cada variável, chaveada pelo id; ausente = `ESCALA_AUTO`. */
  readonly escalas: Readonly<Record<string, EscalaVar>>;
  readonly onAlternarPena: (pena: PenaLegenda) => void;
  readonly onMudarEscala: (varId: string, escala: EscalaVar) => void;
}

export function LegendaOperacao({
  defaults,
  ligadas,
  porIdDefinicao,
  cores,
  foco,
  escalas,
  onAlternarPena,
  onMudarEscala,
}: LegendaOperacaoProps) {
  return (
    <Card data-testid="operate-trend-legend" className="divide-y divide-border">
      {defaults.map((pena) => {
        const definicao = porIdDefinicao.get(pena.id);
        const ligada = ligadas.has(pena.id);
        return (
          <div
            key={pena.id}
            data-testid="operate-trend-legend-item"
            data-var-id={pena.id}
            className="flex items-center gap-3 px-4 py-2 transition-colors duration-[var(--duration-fast)] hover:bg-surface-2"
          >
            {/* Só o trecho identificador é `label`: o editor de escala divide a linha e não
                pode alternar a pena quando o operador clica num campo dele. */}
            <label className="flex grow cursor-pointer items-center gap-3">
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
            </label>
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
            <EditorEscala
              escala={escalas[pena.id] ?? ESCALA_AUTO}
              prefixoTestid="operate"
              aoMudar={(escala) => {
                onMudarEscala(pena.id, escala);
              }}
            />
          </div>
        );
      })}
    </Card>
  );
}
