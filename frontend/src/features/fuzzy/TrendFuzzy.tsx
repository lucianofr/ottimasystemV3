import { useMemo, useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { referenciaPersistidaS, useBordaViva, type LeituraViva } from "../trend/bordaViva";
import { JanelaTempo } from "../trend/JanelaTempo";
import { type BadgeLegenda, type LinhaLegenda, PainelLegendaTrend } from "../trend/PainelLegendaTrend";
import { TrendChart } from "../trend/TrendChart";
import { CLASSES_PENA, LIMITE_PENAS } from "../trend/trendTheme";
import { useJanelaDeslizante } from "../trend/useJanelaDeslizante";
import {
  mesclarHistoricoFuzzyVivo,
  montarMatrizFuzzy,
  resumirSeriesFuzzy,
} from "./historicoFuzzy";
import type { FuzzyNodeOut, FuzzyState } from "./types";
import { useHistoryFuzzy } from "./useHistoryFuzzy";

/**
 * Trend do bloco fuzzy (ADR-030) — espelho do trend de engenharia (`../trend/TrendPage.tsx`):
 * reusa `TrendChart`/`JanelaTempo`/`useJanelaDeslizante` (compartilhados entre as três telas
 * de trend do app) e o mesmo teto de 6 penas (`LIMITE_PENAS`) — não o teto de 8 do trend de
 * operação MPC, que é outro caso de uso (`TETO_PENAS_OPERACAO`, `../operate/trendOperacao.ts`).
 *
 * `TrendChart.ids` é `number[]` (identidade estrutural do gráfico/chave de escala) — as
 * portas fuzzy são strings (`IN1`..`OUTn`, ADR-029), então a posição de cada porta na lista
 * ordenada de variáveis do bloco vira o id numérico local; a ordenação nunca muda durante a
 * vida do painel (mesmo bloco fuzzy aberto), então a mesma porta sempre resolve o mesmo id.
 */

const JANELA_DEFAULT_SEGUNDOS = 1800;

interface VarSelecionavel {
  readonly port: string;
  readonly name: string;
  readonly eu: string | null;
}

function rotuloVarFuzzy(v: VarSelecionavel): string {
  return v.eu ? `${v.port} — ${v.name} (${v.eu})` : `${v.port} — ${v.name}`;
}

export function TrendFuzzy({
  flowId,
  blockId,
  no,
  estado,
}: {
  flowId: number;
  blockId: string;
  no: FuzzyNodeOut;
  /** Último `fuzzy.state` do bloco (o pai já assina `fuzzy_state` e o tem em mãos). */
  estado: FuzzyState | undefined;
}) {
  const variaveis: VarSelecionavel[] = useMemo(
    () => [
      ...no.inputs.map((v) => ({ port: v.port, name: v.name, eu: null })),
      ...no.outputs.map((v) => ({ port: v.port, name: v.name, eu: v.eu ?? null })),
    ],
    [no],
  );
  const idPorPorta = useMemo(() => new Map(variaveis.map((v, i) => [v.port, i + 1])), [variaveis]);
  const porPorta = useMemo(() => new Map(variaveis.map((v) => [v.port, v])), [variaveis]);

  const [selecionadas, setSelecionadas] = useState<string[]>(() =>
    variaveis.slice(0, LIMITE_PENAS).map((v) => v.port),
  );
  const [janelaSegundos, setJanelaSegundos] = useState(JANELA_DEFAULT_SEGUNDOS);
  const deslizante = useJanelaDeslizante(janelaSegundos);
  const historico = useHistoryFuzzy(flowId, blockId, selecionadas, janelaSegundos, deslizante.fimEpochS);

  // Ponta viva: o histórico do TimescaleDB desenha o passado até agora e daí em diante o
  // gráfico cresce a cada `fuzzy.state`, sem esperar o poll de 5 s. Reload cai no mesmo
  // caminho — busca o histórico de novo e recomeça a acumular.
  const leiturasVivas = useMemo(() => {
    const mapa = new Map<string, LeituraViva>();
    // Quadro inválido não plota: o valor não vale (o pai já marca INVÁLIDO na plaqueta).
    if (estado?.ok !== true) return mapa;
    for (const v of [...estado.inputs, ...estado.outputs]) {
      if (v.v !== null) mapa.set(v.port, { ts: estado.ts, v: v.v });
    }
    return mapa;
  }, [estado]);
  const bordaViva = useBordaViva(leiturasVivas, janelaSegundos, deslizante.aoVivo);

  // Uma resposta só alimenta gráfico e legenda: mesclada aqui, os dois veem a mesma ponta.
  const resposta = useMemo(
    () => (historico.data ? mesclarHistoricoFuzzyVivo(historico.data, bordaViva) : null),
    [historico.data, bordaViva],
  );

  const dados = useMemo(
    () => (resposta ? montarMatrizFuzzy(resposta, selecionadas) : null),
    [resposta, selecionadas],
  );
  // Referência de "parou de reportar" = histórico PERSISTIDO (ver `referenciaPersistidaS`).
  const resumos = resposta
    ? resumirSeriesFuzzy(
        resposta,
        selecionadas,
        referenciaPersistidaS(historico.data?.series ?? []),
      )
    : [];
  const ids = selecionadas.map((port) => idPorPorta.get(port) ?? 0);
  const rotulos = selecionadas.map((port) => {
    const v = porPorta.get(port);
    return v ? rotuloVarFuzzy(v) : port;
  });

  function alternar(port: string): void {
    setSelecionadas((atual) => {
      if (atual.includes(port)) return atual.filter((p) => p !== port);
      if (atual.length >= LIMITE_PENAS) return atual;
      return [...atual, port];
    });
  }

  return (
    <div className="space-y-3" data-testid="fuzzy-trend">
      <div className="flex items-center justify-between">
        <h3 className="plaqueta text-xs text-fg-muted">Trend</h3>
        <div className="flex items-center gap-3">
          {historico.data && (
            <span
              data-testid="fuzzy-trend-mode"
              className="plaqueta rounded-sm border border-border bg-well px-2 py-1 text-xs text-fg-muted"
            >
              {historico.data.mode === "1m" ? "1 min" : "bruto"}
            </span>
          )}
          <JanelaTempo prefixoTestid="fuzzy-trend" segundos={janelaSegundos} onChange={setJanelaSegundos} />
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="fuzzy-trend-janela-voltar"
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
              data-testid="fuzzy-trend-janela-avancar"
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
              data-testid="fuzzy-trend-janela-reset"
              onClick={() => {
                deslizante.reset();
              }}
            >
              Reset
            </Button>
          </div>
        </div>
      </div>

      <div className="flex gap-4">
        <Card className="w-72 shrink-0 p-3">
          <p className="plaqueta text-xs text-fg-muted">
            Variáveis ({String(selecionadas.length)}/{String(LIMITE_PENAS)})
          </p>
          <div data-testid="fuzzy-trend-selector" className="mt-2 max-h-96 overflow-y-auto">
            {variaveis.map((v) => (
              <label
                key={v.port}
                data-testid="fuzzy-trend-option"
                data-var-port={v.port}
                className="flex cursor-pointer items-center gap-2 border-b border-border py-1.5 last:border-b-0"
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={selecionadas.includes(v.port)}
                  onChange={() => {
                    alternar(v.port);
                  }}
                />
                <span className="plaqueta grow text-xs">{rotuloVarFuzzy(v)}</span>
              </label>
            ))}
          </div>
        </Card>

        <div className="grow space-y-3">
          {selecionadas.length === 0 && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Selecione até {String(LIMITE_PENAS)} variáveis para exibir</p>
            </Card>
          )}

          {historico.isError && (
            <p role="alert" data-testid="fuzzy-trend-error" className="text-sm text-alarm">
              {historico.error.message}
            </p>
          )}

          {selecionadas.length > 0 && !dados && !historico.isError && (
            <Card className="p-6">
              <p className="text-sm text-fg-muted">Carregando…</p>
            </Card>
          )}

          {dados && (
            <TrendChart dados={dados} ids={ids} rotulos={rotulos} janelaSegundos={janelaSegundos} escalas={{}} />
          )}

          {resumos.length > 0 && (
            <PainelLegendaTrend
              testId="fuzzy-trend-legend"
              linhas={resumos.map((resumo, indice) => {
                const v = porPorta.get(resumo.varId);
                const badges: BadgeLegenda[] = [];
                if (resumo.semDado) {
                  badges.push({
                    testId: "fuzzy-trend-legend-sem-dado",
                    texto: "SEM DADO",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                const linha: LinhaLegenda = {
                  chave: resumo.varId,
                  testId: "fuzzy-trend-legend-item",
                  className: "flex items-center gap-3 px-3 py-2",
                  identificacao: (
                    <>
                      <span
                        aria-hidden="true"
                        className={cn("h-1 w-6 shrink-0", CLASSES_PENA[indice % CLASSES_PENA.length])}
                      />
                      <span className="plaqueta grow text-xs">
                        {v ? `${v.port} — ${v.name}` : resumo.varId}
                      </span>
                    </>
                  ),
                  badges,
                  valorEu: { valor: resumo.valor, eu: v?.eu ?? "", muted: resumo.semDado },
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
