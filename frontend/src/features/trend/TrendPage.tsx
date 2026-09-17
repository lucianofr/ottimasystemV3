import { useMemo, useRef, useState } from "react";

import { useAssinaturaOpcValues, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { baixarBlob } from "../../lib/arquivos";
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
import {
  ESCALA_AUTO,
  foraDaFaixa,
  gravarEscalas,
  lerEscalas,
  limparEscalas,
  type EscalaVar,
} from "./escalas";
import { montarCsvTrend, nomeCsvTrend, recortarEmX } from "./exportarCsv";
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
  // Tag dona do único eixo Y desenhado (mesma política do trend de operação): com um eixo por
  // tag, seis penas comiam seis colunas de eixo à esquerda do gráfico. A última tag marcada
  // assume o eixo; clicar no nome na legenda traz o eixo para ela sem mexer na seleção.
  const [foco, setFoco] = useState<number | null>(null);
  // Índice do carimbo sob o ponteiro (publicado pelo gráfico): a legenda lê dali o valor de
  // cada pena no instante apontado, ao lado do valor corrente — nunca no lugar dele.
  const [idxCursor, setIdxCursor] = useState<number | null>(null);
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
    () =>
      (resposta
        ? montarMatriz(resposta, selecionadas, referenciaPersistidaS(historico.data?.series ?? []))
        : null),
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
      const restantes = selecionadas.filter((id) => id !== tagId);
      setSelecionadas(restantes);
      // O eixo desenhado é de uma tag que está no gráfico: desmarcar a dona passa o eixo para
      // a primeira tag que sobrou (ou nenhuma, se essa era a última).
      if (foco === tagId) setFoco(restantes[0] ?? null);
      setAviso(null);
      return;
    }
    if (selecionadas.length >= LIMITE_PENAS) {
      setAviso(`Máximo de ${String(LIMITE_PENAS)} penas por gráfico`);
      return;
    }
    setSelecionadas([...selecionadas, tagId]);
    setFoco(tagId);
    setAviso(null);
  }

  /** Valor da pena `indice` no carimbo sob o ponteiro. A pena `indice` desenha a coluna
   *  `indice + 1` da matriz (a coluna 0 é o tempo) — mesma matriz do gráfico, sem segundo
   *  caminho de número. `null` = ponteiro fora do gráfico OU silêncio da pena naquele carimbo:
   *  a legenda escreve coluna vazia, nunca zero. */
  function valorNoCursor(indice: number): number | null {
    if (idxCursor === null || dados === null) return null;
    const valor = dados[indice + 1]?.[idxCursor] ?? null;
    return valor !== null && Number.isFinite(valor) ? valor : null;
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

  function exportarCsv(): void {
    // `dados` é a MESMA matriz que o <TrendChart> desenha (inclui a ponta viva do WS e os gaps),
    // recortada na faixa VISÍVEL: com zoom em X aplicado, a janela buscada é maior do que a que
    // o engenheiro está vendo, e o arquivo tem de ser o que está na tela.
    if (!dados || !resposta) return;
    const matriz = recortarEmX(dados, chartRef.current?.faixaX() ?? null);
    const csv = montarCsvTrend(
      matriz,
      selecionadas.map((id) => ({
        rotulo: porId.get(id)?.name ?? String(id),
        eu: porId.get(id)?.eu ?? "",
      })),
    );
    baixarBlob(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
      nomeCsvTrend(matriz, resposta.mode),
    );
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
              data-testid="trend-export-csv"
              disabled={!dados}
              onClick={exportarCsv}
            >
              Exportar CSV
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
              fimEpochS={deslizante.fimEpochS}
              escalas={escalas}
              foco={foco}
              onCursorIdx={setIdxCursor}
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
                // Pena cortada pela moldura: a faixa fixada não alcança o valor de agora.
                // Sem isto a linha some sem explicação e o engenheiro conclui que a
                // variável parou de historiar (achado de campo) — mesma família de
                // `SEM DADO`: aviso na legenda quando o gráfico não pode mostrar a pena.
                const escalaDaTag = escalas[String(resumo.tagId)] ?? ESCALA_AUTO;
                if (foraDaFaixa(escalaDaTag, resumo.valor)) {
                  badges.push({
                    testId: "trend-legend-fora-escala",
                    texto: "FORA DA ESCALA",
                    className: "plaqueta rounded-sm border border-warn px-1.5 text-xs text-warn-fg",
                  });
                }
                const donaDoEixo = resumo.tagId === foco;
                if (donaDoEixo) {
                  badges.push({ texto: "Eixo Y", className: "plaqueta text-xs text-fg-muted" });
                }
                const linha: LinhaLegenda = {
                  chave: String(resumo.tagId),
                  testId: "trend-legend-item",
                  dataAttrs: { "data-tag-id": String(resumo.tagId) },
                  className: "flex items-center gap-3 px-3 py-2",
                  identificacao: (
                    // `aria-current`, não `aria-pressed`: o eixo é de uma tag só, então marcar
                    // uma desmarca a outra sem o engenheiro tocar nela — seleção única, não um
                    // interruptor por linha. Clicar aqui NUNCA tira a pena do gráfico: quem
                    // liga e desliga pena é o seletor de tags à esquerda.
                    <button
                      type="button"
                      aria-current={donaDoEixo ? "true" : undefined}
                      title="Trazer o eixo Y para esta tag"
                      className="focus-ring flex min-h-6 grow cursor-pointer items-center gap-3 text-left"
                      onClick={() => {
                        setFoco(resumo.tagId);
                      }}
                    >
                      <span
                        aria-hidden="true"
                        className={cn("h-1 w-6 shrink-0", CLASSES_PENA[indice % CLASSES_PENA.length])}
                      />
                      <span className="plaqueta grow text-xs">
                        {tag?.name ?? String(resumo.tagId)}
                      </span>
                    </button>
                  ),
                  badges,
                  valorEu: {
                    valor: resumo.valor,
                    eu: tag?.eu ?? "",
                    muted: resumo.bad || resumo.semDado,
                    // Duas colunas, nunca substituição: o valor corrente continua na tela
                    // enquanto o engenheiro inspeciona um instante passado no gráfico.
                    valorCursor: valorNoCursor(indice),
                    testIdValorCursor: "trend-legend-valor-cursor",
                  },
                  filhoEscala: (
                    <EditorEscala
                      escala={escalaDaTag}
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
