import { expect, test } from "@playwright/test";

import type { HistoryResponse, HistorySeries } from "../../lib/api";
import {
  acumularPontosVivos,
  mesclarHistoricoVivo,
  referenciaPersistidaS,
  type PontoVivo,
} from "./bordaViva";
import { montarMatriz, resumirSeries } from "./useHistory";

/** Base arbitrária: só os deslocamentos em segundos importam. */
const T0 = Date.parse("2026-01-01T12:00:00Z") / 1000;

function carimbo(deslocamentoS: number): string {
  return new Date((T0 + deslocamentoS) * 1000).toISOString();
}

/** Série sintética boa: uma amostra a cada `passoS`, de 0 até `ateS` inclusive. */
function serie(tagId: number, passoS: number, ateS: number, valor: number): HistorySeries {
  const t: string[] = [];
  for (let d = 0; d <= ateS; d += passoS) t.push(carimbo(d));
  return { tag_id: tagId, t, v: t.map(() => valor), q: t.map(() => 0) };
}

function resposta(modo: HistoryResponse["mode"], series: HistorySeries[]): HistoryResponse {
  return { mode: modo, start: carimbo(0), end: carimbo(1800), series };
}

const TAG = 1;
const OUTRA = 2;

function vivos(
  entradas: Readonly<Record<string, readonly PontoVivo[]>>,
): ReadonlyMap<string, readonly PontoVivo[]> {
  return new Map(Object.entries(entradas));
}

// ----------------------------------------------------------------------------------------
// Acúmulo do buffer da borda viva
// ----------------------------------------------------------------------------------------

test("leitura nova empilha um ponto; a mesma leitura de novo não muda nada", () => {
  const leitura = new Map([[String(TAG), { ts: carimbo(30), v: 7 }]]);

  const primeiro = acumularPontosVivos(new Map(), leitura, T0);
  expect(primeiro).not.toBeNull();
  expect([...primeiro!.get(String(TAG))!]).toEqual([{ t: T0 + 30, v: 7 }]);

  // Mesmo carimbo: o provider republica o lote a cada flush, mas o ponto já entrou. Sem este
  // `null` o `setState` do hook criaria um mapa novo por flush (250 ms) e re-renderizaria a
  // árvore do trend sem nenhum dado novo.
  expect(acumularPontosVivos(primeiro!, leitura, T0)).toBeNull();
});

test("ponto que saiu da janela é descartado ao empilhar o próximo", () => {
  const antigo = vivos({ [String(TAG)]: [{ t: T0, v: 1 }] });
  const leitura = new Map([[String(TAG), { ts: carimbo(600), v: 2 }]]);

  // Corte = fim − janela: o ponto de T0 está fora dela.
  const depois = acumularPontosVivos(antigo, leitura, T0 + 300);

  expect([...depois!.get(String(TAG))!]).toEqual([{ t: T0 + 600, v: 2 }]);
});

test("pena que saiu da seleção envelhece e sai do buffer sem forçar render", () => {
  // Pena desligada pela legenda para de aparecer em `leituras`: sem poda de TODAS as entradas
  // ela ficaria no buffer até o fim da sessão, custando cópia de array a cada mescla.
  const antigo = vivos({ [String(TAG)]: [{ t: T0, v: 1 }], [String(OUTRA)]: [{ t: T0, v: 9 }] });
  const leitura = new Map([[String(TAG), { ts: carimbo(600), v: 2 }]]);

  const depois = acumularPontosVivos(antigo, leitura, T0 + 300);

  expect([...depois!.keys()]).toEqual([String(TAG)]);

  // Só a poda não é motivo de render: ponto fora da janela nunca chegaria ao gráfico.
  expect(acumularPontosVivos(antigo, new Map(), T0 + 300)).toBeNull();
});

// ----------------------------------------------------------------------------------------
// Merge com o histórico do TimescaleDB — a regressão: a ponta viva não chegava ao gráfico
// ----------------------------------------------------------------------------------------

test("raw: ponto vivo mais novo que o histórico entra no eixo x do gráfico", () => {
  // Histórico até 100 s (o poll é de 5 s, então a ponta REST está sempre atrasada) e uma
  // leitura ao vivo em 104 s, como chega pelo WS.
  const resp = resposta("raw", [serie(TAG, 10, 100, 5)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 104, v: 9 }] }));
  const [x, pena] = montarMatriz(mesclado, [TAG]);

  expect(x[x.length - 1]).toBe(T0 + 104);
  expect(pena[pena.length - 1]).toBe(9);
  // O histórico anterior continua desenhado: a borda viva ADENSA, não substitui.
  expect(x[0]).toBe(T0);
  expect(x.length).toBe(12); // 0,10,…,100 (11) + 104

  // A legenda lê a mesma resposta mesclada: gráfico e legenda nunca se contradizem.
  expect(resumirSeries(mesclado, [TAG])[0]).toEqual({
    tagId: TAG,
    valor: 9,
    bad: false,
    semDado: false,
  });
});

test("ponto vivo em carimbo que o histórico já trouxe não duplica a amostra", () => {
  const resp = resposta("raw", [serie(TAG, 10, 100, 5)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 100, v: 42 }] }));
  const [x] = montarMatriz(mesclado, [TAG]);

  expect(x.length).toBe(11);
  // O histórico persistido manda: é a mesma amostra que o recorder gravou.
  expect(mesclado.series[0].v[10]).toBe(5);
});

test("cada pena recebe só a sua borda viva", () => {
  const resp = resposta("raw", [serie(TAG, 10, 100, 5), serie(OUTRA, 10, 100, 7)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 104, v: 9 }] }));
  const [x, umaPena, outraPena] = montarMatriz(mesclado, [TAG, OUTRA]);

  expect(x[x.length - 1]).toBe(T0 + 104);
  expect(umaPena[umaPena.length - 1]).toBe(9);
  // A outra tag não recebeu leitura: carry-forward legítimo (4 s de silêncio < teto de 20 s).
  expect(outraPena[outraPena.length - 1]).toBe(7);
});

test("1m: a vista agregada também recebe a borda viva", () => {
  // `RAW_WINDOW_HOURS` é 2 h, então qualquer janela de turno (8 h) cai no modo agregado —
  // não é canto. Gatear a borda viva por modo só mudaria o defeito de lugar: o trend de
  // operação MPC (`mesclarSeriesVivas`) mescla nos dois modos, e as três telas têm de ter o
  // mesmo comportamento. O modo escolhe a resolução do PASSADO, não se a ponta é viva.
  const resp = resposta("1m", [serie(TAG, 60, 600, 5)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 800, v: 9 }] }));
  const [x, pena] = montarMatriz(mesclado, [TAG]);

  expect(x[x.length - 1]).toBe(T0 + 800);
  expect(pena[pena.length - 1]).toBe(9);
  // O passado agregado continua desenhado inteiro: a borda viva ACRESCENTA.
  expect(x[0]).toBe(T0);
  expect(x.length).toBe(12); // 0,60,…,600 (11) + 800
});

test("1m: pena viva não marca SEM DADO na vizinha saudável com bucket atrasado", () => {
  // O caso do modo agregado: os buckets do TimescaleDB materializam com ~196 s de atraso, e o
  // teto de carry-forward é 120 s. Se a pena que já recebeu ponto vivo puxar a referência de
  // "agora" para o relógio de parede, a vizinha saudável (mesmo atraso de bucket, só sem ponto
  // vivo ainda — o heartbeat do worker é de 10 s) apareceria com SEM DADO na legenda.
  const resp = resposta("1m", [serie(TAG, 60, 600, 5), serie(OUTRA, 60, 600, 7)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 800, v: 9 }] }));
  const referencia = referenciaPersistidaS(resp.series);

  const resumos = resumirSeries(mesclado, [TAG, OUTRA], referencia);

  expect(resumos[0]).toEqual({ tagId: TAG, valor: 9, bad: false, semDado: false });
  expect(resumos[1]).toEqual({ tagId: OUTRA, valor: 7, bad: false, semDado: false });

  // Sem a referência persistida, a vizinha saudável era acusada de SEM DADO.
  expect(resumirSeries(mesclado, [TAG, OUTRA])[1].semDado).toBe(true);
});

test("pena que realmente parou de reportar continua marcada como SEM DADO", () => {
  // A referência persistida não pode virar anistia: a pena morta (calou 300 s antes do fim do
  // histórico, teto de 120 s no modo 1m) segue acusada.
  const resp = resposta("1m", [serie(TAG, 60, 600, 5), serie(OUTRA, 60, 300, 7)]);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 800, v: 9 }] }));

  const resumos = resumirSeries(mesclado, [TAG, OUTRA], referenciaPersistidaS(resp.series));

  expect(resumos[1].semDado).toBe(true);
  expect(resumos[1].valor).toBeNull();
});

test("tag sem amostra persistida na janela desenha só com a borda viva", () => {
  // O router agrupa o que o banco devolveu: tag recém-criada (ou recorder que acabou de subir)
  // não vem como série nenhuma. Sem esta série sintética a pena ficaria vazia para sempre,
  // mesmo com valor chegando pelo WS.
  const resp = resposta("raw", []);
  const mesclado = mesclarHistoricoVivo(resp, vivos({ [String(TAG)]: [{ t: T0 + 4, v: 3 }] }));
  const [x, pena] = montarMatriz(mesclado, [TAG]);

  expect(x).toEqual([T0 + 4]);
  expect(pena).toEqual([3]);
});

test("sem borda viva a resposta passa inalterada", () => {
  const resp = resposta("raw", [serie(TAG, 10, 100, 5)]);

  expect(mesclarHistoricoVivo(resp, new Map())).toBe(resp);
});
