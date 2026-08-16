import { useMemo, useRef, useState } from "react";

import { useAssinaturaOpcValues, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { useConnections } from "../connections/useConnections";
import { useActiveProject } from "../projects/useProjects";
import {
  mesclarHistoricoVivo,
  referenciaPersistidaS,
  useBordaViva,
  type LeituraViva,
} from "./bordaViva";
import { EditorEscala } from "./EditorEscala";
import { ESCALA_AUTO, gravarEscalas, lerEscalas, limparEscalas, type EscalaVar } from "./escalas";
import { JanelaTempo } from "./JanelaTempo";
import {
  type BadgeLegenda,
  type LinhaLegenda,
  PainelLegendaTrend,
} from "./PainelLegendaTrend";
import { TrendChart, type TrendChartHandle } from "./TrendChart";
import { tagDoProjeto } from "./tagsDoProjeto";
import { CLASSES_PENA, LIMITE_PENAS } from "./trendTheme";
import { montarMatriz, resumirSeries, useHistory, useTags } from "./useHistory";
import { useJanelaDeslizante } from "./useJanelaDeslizante";

/** Janela default: 30 min (era o preset "30m" do seletor que o JanelaTempo substitui). */
const JANELA_DEFAULT_SEGUNDOS = 1800;

/** O engenheiro precisa saber quando está olhando agregado, não amostra bruta (spec F2 §9.2). */
const ROTULO_MODO: Record<"raw" | "1m", string> = { raw: "bruto", "1m": "1 min" };

/** Escalas Y por variável persistem por navegador, não por projeto: preferência de layout,
 *  não dado de processo (mesmo raciocínio de `ottima.operate.escalas.v1`). */
const CHAVE_ESCALAS = "ottima.trend.escalas.v1";

export function TrendPage() {
  const [selecionadas, setSelecionadas] = useState<number[]>([]);
  const [janelaSegundos, setJanelaSegundos] = useState(JANELA_DEFAULT_SEGUNDOS);
  const [aviso, setAviso] = useState<string | null>(null);
  const [escalas, setEscalas] = useState<Record<string, EscalaVar>>(() =>
    lerEscalas(CHAVE_ESCALAS),
  );
  const chartRef = useRef<TrendChartHandle>(null);

  const deslizante = useJanelaDeslizante(janelaSegundos);
  const projeto = useActiveProject();
  const conexoes = useConnections(projeto.data?.id ?? null);
  const tags = useTags();
  const historico = useHistory(selecionadas, janelaSegundos, deslizante.fimEpochS);

  // Ponta viva (`opc.values` via WS): o histórico do TimescaleDB desenha o passado até agora e
  // daí em diante o gráfico cresce por mensagem, sem esperar o poll de 5 s. Reload cai no mesmo
  // caminho — busca o histórico de novo e recomeça a acumular.
  useAssinaturaOpcValues(selecionadas);
  const { tagValues } = useCanalAoVivo();
  const leiturasVivas = useMemo(() => {
    const mapa = new Map<string, LeituraViva>();
    for (const tagId of selecionadas) {
      const leitura = tagValues.get(tagId);
      // Qualidade ruim/valor ausente não vira ponto: o `q === 2` que abre o gap chega
      // persistido no próximo poll (ver `LeituraViva`).
      if (leitura === undefined || !leitura.ok || leitura.v === null) continue;
      mapa.set(String(tagId), { ts: leitura.ts, v: leitura.v });
    }
    return mapa;
  }, [tagValues, selecionadas]);
  const bordaViva = useBordaViva(leiturasVivas, janelaSegundos, deslizante.aoVivo);

  // Uma resposta só alimenta gráfico e legenda: mesclada aqui, os dois veem a mesma ponta.
  const resposta = useMemo(
    () => (historico.data ? mesclarHistoricoVivo(historico.data, bordaViva) : null),
    [historico.data, bordaViva],
  );

  // `selecionadas` é estado: a identidade só muda quando a seleção muda de fato.
  const dados = useMemo(
    () => (resposta ? montarMatriz(resposta, selecionadas) : null),
    [resposta, selecionadas],
  );
  // A referência de "parou de reportar" é a do histórico PERSISTIDO, não da resposta mesclada:
  // ver `referenciaPersistidaS`. O valor exibido segue vindo da ponta viva.
  const resumos = resposta
    ? resumirSeries(resposta, selecionadas, referenciaPersistidaS(historico.data?.series ?? []))
    : [];

  // Escopo por projeto ativo: o worker só reconcilia o projeto ativo (ADR-017) e uma tag
  // calculada pertence direto ao projeto (ADR-033) — fora desse recorte a pena desenharia
  // vazia para sempre. `GET /api/tags` não aceita `project_id`.
  const idsConexao = new Set((conexoes.data ?? []).map((conexao) => conexao.id));
  const projetoAtivoId = projeto.data?.id ?? null;
  const listaTags = (tags.data ?? []).filter(
    (tag) => projetoAtivoId !== null && tagDoProjeto(tag, idsConexao, projetoAtivoId),
  );

  const porId = new Map(listaTags.map((tag) => [tag.id, tag]));
  const rotulos = selecionadas.map((id) => porId.get(id)?.name ?? String(id));

  if (projeto.data === null && projeto.isSuccess) {
    return (
      <section className="space-y-4">
        <h1 className="plaqueta text-sm">Trend</h1>
        <p data-testid="trend-no-project" className="text-sm text-fg-muted">
          Nenhum projeto ativo: ative um projeto para exibir tendências.
        </p>
      </section>
    );
  }

  function alternar(tagId: number): void {
    if (selecionadas.includes(tagId)) {
      setSelecionadas(selecionadas.filter((id) => id !== tagId));
      setAviso(null);
      return;
    }
    if (selecionadas.length >= LIMITE_PENAS) {
      setAviso(`Máximo de ${String(LIMITE_PENAS)} penas por gráfico`);
      return;
    }
    setSelecionadas([...selecionadas, tagId]);
    setAviso(null);
  }

  function definirEscala(tagId: number, escala: EscalaVar): void {
    setEscalas((atual) => {
      const proximo = { ...atual, [String(tagId)]: escala };
      gravarEscalas(CHAVE_ESCALAS, proximo);
      return proximo;
    });
  }

  function resetLayout(): void {
    deslizante.reset();
    chartRef.current?.resetZoom();
    // Reset completo: escalas Y fixadas à mão também voltam ao autoscale (e a preferência
    // persistida some — senão o próximo reload ressuscitaria a escala que o reset apagou).
    limparEscalas(CHAVE_ESCALAS);
    setEscalas({});
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Trend</h1>
        <div className="flex items-center gap-3">
          {historico.data && (
            <span
              data-testid="trend-mode"
              className="plaqueta rounded-sm border border-border bg-well px-2 py-1 text-xs text-fg-muted"
            >
              {ROTULO_MODO[historico.data.mode]}
            </span>
          )}
          <JanelaTempo
            prefixoTestid="trend"
            segundos={janelaSegundos}
            onChange={setJanelaSegundos}
          />
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="trend-janela-voltar"
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
              data-testid="trend-janela-avancar"
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
              data-testid="trend-janela-reset"
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
            Tags ({String(selecionadas.length)}/{String(LIMITE_PENAS)})
          </p>
          {(tags.isPending || conexoes.isPending) && (
            <p className="mt-2 text-sm text-fg-muted">Carregando…</p>
          )}
          {tags.isError && (
            <p role="alert" className="mt-2 text-sm text-alarm">
              Falha ao consultar tags
            </p>
          )}
          {tags.isSuccess && conexoes.isSuccess && listaTags.length === 0 && (
            <p className="mt-2 text-sm text-fg-muted">Nenhuma tag cadastrada</p>
          )}
          <div data-testid="trend-tag-selector" className="mt-2 max-h-96 overflow-y-auto">
            {listaTags.map((tag) => (
              <label
                key={tag.id}
                data-testid="trend-tag-option"
                data-tag-id={tag.id}
                className="flex cursor-pointer items-center gap-2 border-b border-border py-1.5 last:border-b-0"
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={selecionadas.includes(tag.id)}
                  onChange={() => {
                    alternar(tag.id);
                  }}
                />
                <span className="plaqueta grow text-xs">{tag.name}</span>
                <span className="text-xs text-fg-muted">{tag.eu}</span>
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
              <p className="text-sm text-fg-muted">Selecione até 6 tags para exibir</p>
            </Card>
          )}

          {historico.isError && (
            <p role="alert" data-testid="trend-error" className="text-sm text-alarm">
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
              ids={selecionadas}
              rotulos={rotulos}
              janelaSegundos={janelaSegundos}
              escalas={escalas}
            />
          )}

          {resumos.length > 0 && (
            <PainelLegendaTrend
              testId="trend-legend"
              linhas={resumos.map((resumo, indice) => {
                const tag = porId.get(resumo.tagId);
                const badges: BadgeLegenda[] = [];
                if (resumo.bad) {
                  badges.push({
                    testId: "trend-legend-bad",
                    texto: "BAD",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                // Sem amostra dentro do teto: rótulo próprio, não `BAD`. `BAD` é qualidade
                // ruim que chegou da origem; isto é a aquisição parada. Confundir os dois
                // mandaria o engenheiro depurar o servidor OPC em vez do worker.
                if (resumo.semDado) {
                  badges.push({
                    testId: "trend-legend-sem-dado",
                    texto: "SEM DADO",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                const linha: LinhaLegenda = {
                  chave: String(resumo.tagId),
                  testId: "trend-legend-item",
                  className: "flex items-center gap-3 px-3 py-2",
                  identificacao: (
                    <>
                      <span
                        aria-hidden="true"
                        className={cn("h-1 w-6 shrink-0", CLASSES_PENA[indice % CLASSES_PENA.length])}
                      />
                      <span className="plaqueta grow text-xs">
                        {tag?.name ?? String(resumo.tagId)}
                      </span>
                    </>
                  ),
                  badges,
                  valorEu: { valor: resumo.valor, eu: tag?.eu ?? "", muted: resumo.bad || resumo.semDado },
                  filhoEscala: (
                    <EditorEscala
                      escala={escalas[String(resumo.tagId)] ?? ESCALA_AUTO}
                      prefixoTestid="trend"
                      aoMudar={(escala) => {
                        definirEscala(resumo.tagId, escala);
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
    </section>
  );
}
