import { useMemo, useRef, useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { baixarBlob } from "../../lib/arquivos";
import { cn } from "../../lib/cn";
import {
  escalasPorId,
  mesclarHistoricoFuzzyVivo,
  montarMatrizFuzzy,
  resumirSeriesFuzzy,
} from "../fuzzy/historicoFuzzy";
import { referenciaPersistidaS, useBordaViva } from "../trend/bordaViva";
import { EditorEscala } from "../trend/EditorEscala";
import {
  ESCALA_AUTO,
  foraDaFaixa,
  gravarEscalas,
  lerEscalas,
  limparEscalas,
  type EscalaVar,
} from "../trend/escalas";
import { montarCsvTrend, nomeCsvTrend, recortarEmX } from "../trend/exportarCsv";
import { JanelaTempo } from "../trend/JanelaTempo";
import { type BadgeLegenda, type LinhaLegenda, PainelLegendaTrend } from "../trend/PainelLegendaTrend";
import { TrendChart, type TrendChartHandle } from "../trend/TrendChart";
import { CLASSES_PENA, LIMITE_PENAS } from "../trend/trendTheme";
import { useJanelaDeslizante } from "../trend/useJanelaDeslizante";
import { historicoComLacunas, leiturasVivasMalha, penasIniciais, varsMalha } from "./malhaLogica";
import type { LoopState } from "./types";
import { useHistoryLoop } from "./useHistoryLoop";

/**
 * Trend PV/SP/OUT da malha (RF-646) — espelho de `../fuzzy/TrendFuzzy.tsx` (mesmos controles,
 * mesma janela deslizante, mesmo teto de `LIMITE_PENAS`), com a identidade da pena no `id` de
 * `varsMalha` (`pv`, `sp:1`…) no lugar da porta fuzzy. `TrendChart.ids` é `number[]`: a posição
 * da variável em `varsMalha` vira o id numérico local, estável porque a lista só cresce no fim
 * quando `n_loops` chega. Sem EU: o bloco de malha não publica unidade.
 *
 * O histórico aparece com o flow parado; só a ponta viva depende de `aoVivo` (quadro novo do
 * canal 0), para o quadro retido de antes não entrar no gráfico como se fosse de agora.
 */

const JANELA_DEFAULT_SEGUNDOS = 1800;

export function TrendMalha({
  flowId,
  blockId,
  nLoops,
  estados,
  aoVivo,
}: {
  flowId: number;
  blockId: string;
  nLoops: number;
  /** Um `LoopState` por canal (índice = canal), já assinado pela página. */
  estados: readonly (LoopState | undefined)[];
  /** Portão do canal 0 (`malhaAoVivo`): com o flow parado ou o canal fora, nada entra na borda. */
  aoVivo: boolean;
}) {
  const variaveis = useMemo(() => varsMalha(nLoops), [nLoops]);
  const idPorVar = useMemo(() => new Map(variaveis.map((v, i) => [v.id, i + 1])), [variaveis]);
  const porId = useMemo(() => new Map(variaveis.map((v) => [v.id, v])), [variaveis]);

  const [selecionadas, setSelecionadas] = useState<string[]>(() => penasIniciais(variaveis));
  const [janelaSegundos, setJanelaSegundos] = useState(JANELA_DEFAULT_SEGUNDOS);
  const [aviso, setAviso] = useState<string | null>(null);
  // Escala Y por variável, persistida por flow+bloco e chaveada pelo id da variável.
  const chaveEscalas = `ottima.loop.escalas.v1:${String(flowId)}/${blockId}`;
  const [escalas, setEscalas] = useState<Record<string, EscalaVar>>(() => lerEscalas(chaveEscalas));
  // Variável dona do único eixo Y desenhado (mesma política do trend fuzzy e do de engenharia).
  const [foco, setFoco] = useState<string | null>(() => selecionadas[0] ?? null);
  // Índice do carimbo sob o ponteiro (publicado pelo gráfico), para a coluna de valor no cursor.
  const [idxCursor, setIdxCursor] = useState<number | null>(null);
  const chartRef = useRef<TrendChartHandle>(null);
  const deslizante = useJanelaDeslizante(janelaSegundos);
  const historico = useHistoryLoop(flowId, blockId, selecionadas, janelaSegundos, deslizante.fimEpochS);

  // Ponta viva: o histórico desenha o passado e daí em diante o gráfico cresce a cada
  // `loop.state`, sem esperar o poll de 5 s. Flow parado ou canal fora: borda vazia.
  const leiturasVivas = useMemo(() => leiturasVivasMalha(estados), [estados]);
  const bordaViva = useBordaViva(leiturasVivas, janelaSegundos, deslizante.aoVivo && aoVivo);

  // Referência de "parou de reportar" = histórico PERSISTIDO (ver `referenciaPersistidaS`).
  const referenciaS = useMemo(
    () => referenciaPersistidaS(historico.data?.series ?? []),
    [historico.data],
  );
  // Uma resposta só alimenta gráfico e legenda. A amostra nula atravessa (R11): vira lacuna em
  // `alinharNoEixo`, em vez de o último PV bom ser repetido como se fosse o de agora.
  const resposta = useMemo(
    () =>
      historico.data
        ? mesclarHistoricoFuzzyVivo(historicoComLacunas(historico.data), bordaViva)
        : null,
    [historico.data, bordaViva],
  );
  const dados = useMemo(
    () => (resposta ? montarMatrizFuzzy(resposta, selecionadas, referenciaS) : null),
    [resposta, selecionadas, referenciaS],
  );
  const resumos = resposta ? resumirSeriesFuzzy(resposta, selecionadas, referenciaS) : [];
  const ids = selecionadas.map((id) => idPorVar.get(id) ?? 0);
  const rotulos = selecionadas.map((id) => porId.get(id)?.rotulo ?? id);

  function alternar(id: string): void {
    if (selecionadas.includes(id)) {
      const restantes = selecionadas.filter((s) => s !== id);
      setSelecionadas(restantes);
      if (foco === id) setFoco(restantes[0] ?? null);
      setAviso(null);
      return;
    }
    if (selecionadas.length >= LIMITE_PENAS) {
      setAviso(`Máximo de ${String(LIMITE_PENAS)} penas por gráfico`);
      return;
    }
    setSelecionadas([...selecionadas, id]);
    setFoco(id);
    setAviso(null);
  }

  /** Valor da pena `indice` no carimbo sob o ponteiro — coluna `indice + 1` da mesma matriz do
   *  gráfico. `null` = ponteiro fora ou silêncio da pena ali (coluna vazia, nunca zero). */
  function valorNoCursor(indice: number): number | null {
    if (idxCursor === null || dados === null) return null;
    const valor = dados[indice + 1]?.[idxCursor] ?? null;
    return valor !== null && Number.isFinite(valor) ? valor : null;
  }

  function definirEscala(id: string, escala: EscalaVar): void {
    setEscalas((atual) => {
      const proximo = { ...atual, [id]: escala };
      gravarEscalas(chaveEscalas, proximo);
      return proximo;
    });
  }

  /** Reset completo, igual ao do trend fuzzy: janela ao vivo, zoom limpo e escalas Y de volta
   *  ao autoscale (a preferência persistida some junto). */
  function resetLayout(): void {
    deslizante.reset();
    chartRef.current?.resetZoom();
    limparEscalas(chaveEscalas);
    setEscalas({});
  }

  /** Exporta a mesma matriz do gráfico, recortada na faixa visível (zoom em X incluso). */
  function exportarCsv(): void {
    if (!dados || !resposta) return;
    const matriz = recortarEmX(dados, chartRef.current?.faixaX() ?? null);
    const csv = montarCsvTrend(
      matriz,
      selecionadas.map((id) => ({ rotulo: porId.get(id)?.rotulo ?? id, eu: "" })),
    );
    baixarBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), nomeCsvTrend(matriz, resposta.mode));
  }

  return (
    <div className="space-y-3" data-testid="loop-trend">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">Trend</h3>
        <div className="flex items-center gap-3">
          {historico.data && (
            <span
              data-testid="loop-trend-mode"
              className="plaqueta rounded-sm border border-border bg-well px-2 py-1 text-xs text-fg-muted"
            >
              {historico.data.mode === "1m" ? "1 min" : "bruto"}
            </span>
          )}
          <JanelaTempo prefixoTestid="loop-trend" segundos={janelaSegundos} onChange={setJanelaSegundos} />
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="loop-trend-janela-voltar"
              aria-label="Voltar no tempo"
              onClick={() => {
                deslizante.voltar();
              }}
            >
              {"<"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="loop-trend-janela-avancar"
              aria-label="Avançar no tempo"
              disabled={deslizante.aoVivo}
              onClick={() => {
                deslizante.avancar();
              }}
            >
              {">"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="loop-trend-export-csv"
              disabled={!dados}
              onClick={exportarCsv}
            >
              Exportar CSV
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="loop-trend-janela-reset"
              onClick={resetLayout}
            >
              Reset layout
            </Button>
          </div>
        </div>
      </div>

      <div className="flex gap-4">
        <Card className="w-72 shrink-0 p-3">
          <p className="plaqueta text-xs text-fg-muted">
            Variáveis ({String(selecionadas.length)}/{String(LIMITE_PENAS)})
          </p>
          <div data-testid="loop-trend-selector" className="mt-2 max-h-96 overflow-y-auto">
            {variaveis.map((v) => (
              <label
                key={v.id}
                data-testid="loop-trend-option"
                data-var-id={v.id}
                className="flex cursor-pointer items-center gap-2 border-b border-border py-1.5 last:border-b-0"
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={selecionadas.includes(v.id)}
                  onChange={() => {
                    alternar(v.id);
                  }}
                />
                <span className="plaqueta grow text-xs">{v.rotulo}</span>
              </label>
            ))}
          </div>
          {aviso && (
            <p role="alert" className="mt-2 text-xs text-warn-fg">
              {aviso}
            </p>
          )}
        </Card>

        <div className="grow space-y-3">
          {selecionadas.length === 0 && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Selecione até {String(LIMITE_PENAS)} variáveis para exibir</p>
            </Card>
          )}

          {historico.isError && (
            <p role="alert" data-testid="loop-trend-error" className="text-sm text-alarm">
              {historico.error.message}
            </p>
          )}

          {selecionadas.length > 0 && !dados && !historico.isError && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Carregando…</p>
            </Card>
          )}

          {dados && (
            <TrendChart
              ref={chartRef}
              dados={dados}
              ids={ids}
              rotulos={rotulos}
              janelaSegundos={janelaSegundos}
              fimEpochS={deslizante.fimEpochS}
              escalas={escalasPorId(selecionadas, idPorVar, escalas)}
              foco={foco === null ? null : (idPorVar.get(foco) ?? null)}
              onCursorIdx={setIdxCursor}
            />
          )}

          {resumos.length > 0 && (
            <PainelLegendaTrend
              testId="loop-trend-legend"
              linhas={resumos.map((resumo, indice) => {
                const badges: BadgeLegenda[] = [];
                if (resumo.semDado) {
                  badges.push({
                    testId: "loop-trend-legend-sem-dado",
                    texto: "SEM DADO",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                // Pena cortada pela moldura: a faixa fixada não alcança o valor de agora.
                const escalaDaVar = escalas[resumo.varId] ?? ESCALA_AUTO;
                if (foraDaFaixa(escalaDaVar, resumo.valor)) {
                  badges.push({
                    testId: "loop-trend-legend-fora-escala",
                    texto: "FORA DA ESCALA",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                const donaDoEixo = resumo.varId === foco;
                if (donaDoEixo) {
                  badges.push({ texto: "Eixo Y", className: "plaqueta text-xs text-fg-muted" });
                }
                const linha: LinhaLegenda = {
                  chave: resumo.varId,
                  testId: "loop-trend-legend-item",
                  dataAttrs: { "data-var-id": resumo.varId },
                  className: "flex items-center gap-3 px-3 py-2",
                  identificacao: (
                    // Mesmo contrato do trend de engenharia: seleção única do eixo
                    // (`aria-current`); clicar aqui nunca tira a pena do gráfico.
                    <button
                      type="button"
                      aria-current={donaDoEixo ? "true" : undefined}
                      title="Trazer o eixo Y para esta variável"
                      className="focus-ring flex min-h-6 grow cursor-pointer items-center gap-3 text-left"
                      onClick={() => {
                        setFoco(resumo.varId);
                      }}
                    >
                      <span
                        aria-hidden="true"
                        className={cn("h-1 w-6 shrink-0", CLASSES_PENA[indice % CLASSES_PENA.length])}
                      />
                      <span className="plaqueta grow text-xs">
                        {porId.get(resumo.varId)?.rotulo ?? resumo.varId}
                      </span>
                    </button>
                  ),
                  badges,
                  valorEu: {
                    valor: resumo.valor,
                    eu: "",
                    muted: resumo.semDado,
                    valorCursor: valorNoCursor(indice),
                    testIdValorCursor: "loop-trend-legend-valor-cursor",
                  },
                  filhoEscala: (
                    <EditorEscala
                      escala={escalaDaVar}
                      prefixoTestid="loop-trend"
                      aoMudar={(escala) => {
                        definirEscala(resumo.varId, escala);
                      }}
                    />
                  ),
                };
                return linha;
              })}
            />
          )}
        </div>
      </div>
    </div>
  );
}
