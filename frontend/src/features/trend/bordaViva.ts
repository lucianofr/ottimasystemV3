import { useEffect, useState } from "react";

import type { HistoryResponse } from "../../lib/api";

/**
 * Borda viva dos trends: o histórico do TimescaleDB desenha o passado, o WS adensa a ponta.
 *
 * O trend de operação MPC já fazia isso (`../operate/trendOperacao.ts`, `mesclarSeriesVivas`);
 * o de engenharia e o fuzzy só redesenhavam a janela inteira a cada poll de 5 s, então o mesmo
 * dado aparecia em saltos de 5 s numa tela e ao vivo na outra. Este módulo é a peça que
 * faltava, compartilhada pelas duas — mesma regra em `raw` e em `1m`, como em
 * `mesclarSeriesVivas`: o modo escolhe a resolução do PASSADO, não se a ponta é viva.
 *
 * O merge devolve uma `HistoryResponse` — não colunas de uPlot — de propósito: `montarMatriz`
 * e `resumirSeries` seguem intocados e os dois passam a ver a ponta viva pelo mesmo caminho,
 * então gráfico e legenda não podem se contradizer (o motivo de `resumirSeries` usar o carimbo
 * mais recente da resposta como referência de "agora", `useHistory.ts`).
 */

/** Ponto da ponta viva; `t` em segundos epoch, como o eixo x do uPlot. */
export interface PontoVivo {
  readonly t: number;
  readonly v: number;
}

/** Leitura do canal ao vivo já normalizada pela página: só o que é bom de plotar chega aqui.
 *  Qualidade ruim e valor ausente ficam de fora — o ponto `q === 2` que gera o gap chega
 *  persistido no próximo poll, mesma divisão de trabalho de `mesclarSeriesVivas`. */
export interface LeituraViva {
  readonly ts: string;
  readonly v: number;
}

const VAZIO: ReadonlyMap<string, readonly PontoVivo[]> = new Map();

/**
 * Empilha as leituras que ainda não entraram e envelhece o buffer inteiro pela janela.
 *
 * A poda alcança TODA pena, não só as que receberam leitura nesta passada: a pena desligada
 * pela legenda (ou a tag que parou de reportar) some do buffer uma janela depois, em vez de
 * ficar até o fim da sessão custando cópia de array a cada mescla — a seleção do trend muda em
 * runtime, sem remontar a página (`useAssinaturaOpcValues`), então sem isso o buffer guardaria
 * uma entrada por tag já selecionada alguma vez.
 *
 * Devolve `null` quando nada mudou: o provider republica o lote de `opc.values` a cada flush
 * (250 ms) e o `fuzzy.state` repete o mesmo quadro entre execuções do bloco — sem esse `null`
 * o hook criaria um mapa novo a cada flush e re-renderizaria o trend sem dado novo nenhum.
 */
export function acumularPontosVivos(
  anterior: ReadonlyMap<string, readonly PontoVivo[]>,
  leituras: ReadonlyMap<string, LeituraViva>,
  corteEpochS: number,
): ReadonlyMap<string, readonly PontoVivo[]> | null {
  const proximo = new Map<string, readonly PontoVivo[]>();
  let mudou = false;
  for (const [id, pontos] of anterior) {
    const dentro = pontos.filter((ponto) => ponto.t >= corteEpochS);
    if (dentro.length > 0) proximo.set(id, dentro);
  }
  // A poda sozinha NÃO conta como mudança: ponto fora da janela nunca chega ao gráfico (a
  // mescla só acrescenta o que é mais novo que o histórico), então re-renderizar por causa
  // dela seria puro custo. O mapa podado entra no estado junto da próxima leitura de verdade —
  // que a 4 Hz é logo em seguida.
  for (const [id, leitura] of leituras) {
    const t = Date.parse(leitura.ts) / 1000;
    const pontos = proximo.get(id) ?? [];
    const ultimo = pontos[pontos.length - 1];
    // `<=`: carimbo repetido é o mesmo quadro republicado; carimbo mais antigo é reordenação
    // do barramento — nos dois casos o ponto já está representado.
    if (ultimo !== undefined && t <= ultimo.t) continue;
    proximo.set(id, [...pontos, { t, v: leitura.v }]);
    mudou = true;
  }
  return mudou ? proximo : null;
}

/**
 * Buffer da ponta viva de uma tela de trend. `leituras` precisa vir memoizado por quem chama
 * (a página traduz o canal ao vivo para `LeituraViva` por id).
 *
 * `aoVivo === false` (janela congelada pelo `<`/`>`) devolve vazio sem parar de acumular: a
 * vista congelada não pode ganhar pontos que vazam do fim escolhido pelo operador, mas voltar
 * ao vivo tem de reencontrar a borda já formada.
 */
export function useBordaViva(
  leituras: ReadonlyMap<string, LeituraViva>,
  janelaSegundos: number,
  aoVivo: boolean,
): ReadonlyMap<string, readonly PontoVivo[]> {
  const [pontos, setPontos] = useState(VAZIO);

  useEffect(() => {
    setPontos(
      (atual) => acumularPontosVivos(atual, leituras, Date.now() / 1000 - janelaSegundos) ?? atual,
    );
  }, [leituras, janelaSegundos]);

  return aoVivo ? pontos : VAZIO;
}

/**
 * Referência de "agora" do histórico PERSISTIDO: o carimbo mais recente que o banco devolveu,
 * de qualquer pena. É o que `resumirSeries`/`resumirSeriesFuzzy` precisam receber quando a
 * resposta que elas leem já tem borda viva mesclada — julgar "parou de reportar" contra o
 * relógio de parede acusaria SEM DADO na pena saudável cujo bucket agregado ainda não
 * materializou (~196 s de atraso no modo `1m`).
 */
export function referenciaPersistidaS(
  series: readonly { readonly t: readonly string[] }[],
): number {
  let referencia = Number.NEGATIVE_INFINITY;
  for (const serie of series) {
    const ultimo = serie.t[serie.t.length - 1];
    if (ultimo !== undefined) referencia = Math.max(referencia, Date.parse(ultimo) / 1000);
  }
  return referencia;
}

/**
 * Colunas a ACRESCENTAR a uma série do histórico: só os pontos vivos mais novos que a última
 * amostra persistida. Carimbo que o histórico já trouxe nunca é sobrescrito — histórico e
 * borda viva descrevem a mesma amostra, e o que o recorder gravou é a versão canônica.
 *
 * `vivos` tem de estar em ordem crescente de `t` — `acumularPontosVivos` só empilha ponto mais
 * novo que o último, e o eixo x de `montarMatriz` avança com um cursor por pena, que não sabe
 * voltar. Série sem nenhuma amostra na janela (recorder que acabou de subir, tag recém-criada)
 * recebe a borda inteira: sem isso a pena ficaria vazia mesmo com valor chegando pelo WS.
 */
export function colunasVivas(
  t: readonly string[],
  vivos: readonly PontoVivo[],
): { readonly t: string[]; readonly v: number[] } | null {
  const ultimo = t[t.length - 1];
  const pontaS = ultimo === undefined ? Number.NEGATIVE_INFINITY : Date.parse(ultimo) / 1000;
  const novos = vivos.filter((ponto) => ponto.t > pontaS);
  if (novos.length === 0) return null;
  return {
    t: novos.map((ponto) => new Date(ponto.t * 1000).toISOString()),
    v: novos.map((ponto) => ponto.v),
  };
}

/** Histórico do trend de engenharia com a ponta viva de `opc.values` acrescentada. */
export function mesclarHistoricoVivo(
  resposta: HistoryResponse,
  vivos: ReadonlyMap<string, readonly PontoVivo[]>,
): HistoryResponse {
  if (vivos.size === 0) return resposta;

  let mudou = false;
  const series = resposta.series.map((serie) => {
    const extra = colunasVivas(serie.t, vivos.get(String(serie.tag_id)) ?? []);
    if (extra === null) return serie;
    mudou = true;
    return {
      ...serie,
      t: [...serie.t, ...extra.t],
      v: [...serie.v, ...extra.v],
      // Só leitura boa entra na borda viva (ver `LeituraViva`): qualidade 0 por construção.
      q: [...serie.q, ...extra.t.map(() => 0)],
    };
  });

  // Tag selecionada sem nenhuma amostra na janela não vem como série na resposta (o router
  // agrupa o que o banco devolveu): a pena existe só na borda viva. A comparação é no domínio
  // NUMÉRICO do `tag_id` — comparar a chave textual deixaria uma chave fora do formato
  // `String(tagId)` empurrar série duplicada sobre a que já foi mesclada.
  const persistidas = new Set(resposta.series.map((serie) => serie.tag_id));
  for (const [id, pontos] of vivos) {
    const tagId = Number(id);
    if (!Number.isInteger(tagId) || persistidas.has(tagId) || pontos.length === 0) continue;
    series.push({
      tag_id: tagId,
      t: pontos.map((ponto) => new Date(ponto.t * 1000).toISOString()),
      v: pontos.map((ponto) => ponto.v),
      q: pontos.map(() => 0),
    });
    mudou = true;
  }

  return mudou ? { ...resposta, series } : resposta;
}
