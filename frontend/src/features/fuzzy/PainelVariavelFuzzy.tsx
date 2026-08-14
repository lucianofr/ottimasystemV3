import { useMemo } from "react";

import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { formatarNumero } from "../flows/useFlowStatus";
import {
  ALTURA_VIEWBOX,
  LARGURA_VIEWBOX,
  pontosArea,
  pontosPolilinha,
  rodapeMuDeX,
  rodapeYChapeu,
  silhuetaAgregada,
  xDoMarcador,
} from "./fuzzyMath";
import type { FuzzyVariableOut, FuzzyVarState } from "./types";

/**
 * Painel SVG de uma variável fuzzy (entrada ou saída), ADR-030 — curvas de pertinência da
 * introspecção (`FuzzyIntrospection`, servidor amostra em `N_PONTOS`, o frontend nunca
 * parseia FLL), linha ao vivo do valor crisp e rodapé `μ(x)` sempre; saída ganha a silhueta
 * agregada (ou sombreado por opacidade quando a norma do FLL não é uma das suportadas —
 * `fuzzyMath.ts`) e o rodapé `ŷ` do valor defuzzificado. Sem dependência nova: SVG puro.
 */

/** Paleta de termo — mesmos 8 tokens de série do design system (`--color-pen-1..8`,
 *  `tokens.css`), consumidos como classes Tailwind diretas (SVG é DOM, não canvas: sem
 *  `getComputedStyle`, diferente de `TrendOperacao.tsx`). Literais: o Tailwind extrai
 *  utilitários varrendo o texto-fonte, `stroke-pen-${n}` nunca seria gerado
 *  (`trendTheme.ts:6-9`). */
const PALETA_TERMOS: readonly { readonly stroke: string; readonly fill: string }[] = [
  { stroke: "stroke-pen-1", fill: "fill-pen-1" },
  { stroke: "stroke-pen-2", fill: "fill-pen-2" },
  { stroke: "stroke-pen-3", fill: "fill-pen-3" },
  { stroke: "stroke-pen-4", fill: "fill-pen-4" },
  { stroke: "stroke-pen-5", fill: "fill-pen-5" },
  { stroke: "stroke-pen-6", fill: "fill-pen-6" },
  { stroke: "stroke-pen-7", fill: "fill-pen-7" },
  { stroke: "stroke-pen-8", fill: "fill-pen-8" },
];

const TRANSICAO_OPACIDADE = "transition-opacity duration-[var(--duration-base)] ease-[var(--ease-out)]";
const TRANSICAO_X = "transition-all duration-[var(--duration-base)] ease-[var(--ease-out)]";

export interface PainelVariavelFuzzyProps {
  readonly variavel: FuzzyVariableOut;
  readonly estado: FuzzyVarState | undefined;
  readonly ehSaida: boolean;
  /** `output_eu[port]` — sempre `null` em entradas (o backend não projeta EU de entrada). */
  readonly eu: string | null;
  /** Norma de implicação do 1º rule block do FLL — a implicação é do rule block, não da
   *  variável (`FuzzyRuleBlockOut.implication`); a agregação já é da própria variável
   *  (`FuzzyVariableOut.aggregation`).
   *  ponytail: assume um único rule block para a silhueta; FLL com mais de um bloco ainda
   *  mostra os termos das saídas sombreados por opacidade (fallback sem silhueta) — apertar
   *  se um projeto real usar rule blocks múltiplos por saída. */
  readonly implicacao: string | null;
}

export function PainelVariavelFuzzy({ variavel, estado, ehSaida, eu, implicacao }: PainelVariavelFuzzyProps) {
  // Geometria das curvas só depende da introspecção (estável enquanto o bloco está aberto);
  // sem este memo, ~101 pontos por termo seriam reprojetados a cada quadro do canal (4 Hz).
  const geometria = useMemo(
    () =>
      variavel.terms.map((termo) => ({
        nome: termo.name,
        area: pontosArea(
          variavel.x,
          termo.y,
          variavel.minimum,
          variavel.maximum,
          LARGURA_VIEWBOX,
          ALTURA_VIEWBOX,
        ),
        linha: pontosPolilinha(
          variavel.x,
          termo.y,
          variavel.minimum,
          variavel.maximum,
          LARGURA_VIEWBOX,
          ALTURA_VIEWBOX,
        ),
      })),
    [variavel],
  );
  const grauPorTermo = new Map((estado?.terms ?? []).map((termo) => [termo.term, termo.degree]));
  const termosComGrau = variavel.terms.map((termo) => ({
    y: termo.y,
    grau: grauPorTermo.get(termo.name) ?? 0,
  }));
  const silhueta = ehSaida
    ? silhuetaAgregada(termosComGrau, implicacao, variavel.aggregation ?? null, variavel.x.length)
    : null;
  const marcadorX =
    estado !== undefined && estado.v !== null
      ? xDoMarcador(estado.v, variavel.minimum, variavel.maximum, LARGURA_VIEWBOX)
      : null;

  return (
    <Card className="p-4" data-testid={`fuzzy-painel-${variavel.port}`} data-var-port={variavel.port}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="plaqueta text-[10px] text-fg-muted">{variavel.port}</p>
          <p className="truncate text-sm text-fg" title={variavel.name}>
            {variavel.name}
          </p>
        </div>
        {ehSaida && (variavel.aggregation != null || variavel.defuzzifier != null) && (
          <div className="flex shrink-0 flex-wrap justify-end gap-1">
            {variavel.aggregation != null && (
              <Badge tone="neutral" data-testid="fuzzy-badge-aggregation">
                Agregação: {variavel.aggregation}
              </Badge>
            )}
            {variavel.defuzzifier != null && (
              <Badge tone="neutral" data-testid="fuzzy-badge-defuzzifier">
                {variavel.defuzzifier}
                {variavel.resolution != null ? ` (${String(variavel.resolution)})` : ""}
              </Badge>
            )}
          </div>
        )}
      </div>

      <svg
        aria-hidden="true"
        viewBox={`0 0 ${String(LARGURA_VIEWBOX)} ${String(ALTURA_VIEWBOX)}`}
        className="mt-2 h-28 w-full"
        data-testid={`fuzzy-svg-${variavel.port}`}
      >
        {geometria.map((curva, indice) => {
          const cor = PALETA_TERMOS[indice % PALETA_TERMOS.length];
          const grau = grauPorTermo.get(curva.nome) ?? 0;
          // Sombreado extra proporcional ao grau só na saída sem silhueta calculável (norma
          // fora das 6 suportadas ou `aggregation: none`) — com silhueta, o polígono
          // agregado já comunica a ativação; sombrear os termos por cima duplicaria o sinal.
          const opacidadeGrau = ehSaida && silhueta === null ? grau * 0.5 : 0;
          return (
            <g key={curva.nome} data-testid="fuzzy-termo" data-termo={curva.nome}>
              <polygon className={cn(cor.fill, "opacity-10")} points={curva.area} />
              {opacidadeGrau > 0 && (
                <polygon
                  className={cn(cor.fill, TRANSICAO_OPACIDADE)}
                  style={{ opacity: opacidadeGrau }}
                  points={curva.area}
                />
              )}
              <polyline
                className={cn(cor.stroke, "fill-none")}
                strokeWidth={1.5}
                points={curva.linha}
              />
            </g>
          );
        })}

        {silhueta !== null && (
          <polygon
            className={cn("fill-accent/30 stroke-accent", TRANSICAO_OPACIDADE)}
            strokeWidth={2}
            data-testid="fuzzy-silhueta"
            points={pontosArea(
              variavel.x,
              silhueta,
              variavel.minimum,
              variavel.maximum,
              LARGURA_VIEWBOX,
              ALTURA_VIEWBOX,
            )}
          />
        )}

        {marcadorX !== null && (
          <line
            x1={marcadorX}
            x2={marcadorX}
            y1={0}
            y2={ALTURA_VIEWBOX}
            className={cn("stroke-fg", TRANSICAO_X)}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            data-testid={`fuzzy-marcador-${variavel.port}`}
          />
        )}
      </svg>

      <div className="flex justify-between text-[10px] text-fg-muted">
        <span className="process-value">{formatarNumero(variavel.minimum)}</span>
        <span className="process-value">{formatarNumero(variavel.maximum)}</span>
      </div>

      <p className="mt-2 truncate text-[11px] text-fg-muted" data-testid={`fuzzy-rodape-mu-${variavel.port}`}>
        {rodapeMuDeX(estado?.terms ?? [])}
      </p>
      {ehSaida && (
        <p className="text-[11px] text-fg-muted" data-testid={`fuzzy-rodape-y-${variavel.port}`}>
          {rodapeYChapeu(estado?.v ?? null, eu)}
        </p>
      )}
    </Card>
  );
}
