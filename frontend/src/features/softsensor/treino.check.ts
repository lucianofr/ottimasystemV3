import { expect, test } from "@playwright/test";

import { SOFT_SENSOR_HYPERPARAMS } from "../../lib/contracts.gen";
import type { DatasetOut, SoftSensorBlockOut } from "./types";
import {
  aquecimentoDoModelo,
  ativacaoRecente,
  blocosCompativeis,
  conjuntosCompativeis,
  estadoDoModelo,
  formatarAquecimento,
  formatarMetrica,
  hiperparametrosIniciais,
  precisaAcompanhar,
  problemaDoCampo,
  progressoDoTreino,
  temTrocaPendente,
  validarHiperparametros,
} from "./treino";

/**
 * Funções puras do treino e dos modelos na página "Coleta e treino" (RF-589, RF-584): sem
 * browser, sem backend. As mensagens são o que o engenheiro lê, então ficam pinadas.
 */

function bloco(sobrescreve: Partial<SoftSensorBlockOut> = {}): SoftSensorBlockOut {
  return {
    flow_id: 1,
    flow_name: "flow-a",
    block_id: "ss1",
    label: "ss1",
    method: "esn",
    n_inputs: 3,
    ts_seconds: 10,
    desired_model_id: null,
    active_model_id: null,
    candidate_model_id: null,
    ...sobrescreve,
  };
}

function conjunto(sobrescreve: Partial<DatasetOut> = {}): DatasetOut {
  return {
    id: 1,
    name: "enxofre-a",
    lab_variable_id: 7,
    lab_variable_name: "Enxofre",
    input_tag_ids: [10, 11, 12],
    inputs_meta: [],
    period_s: 60,
    start_ts: "2026-11-01T00:00:00Z",
    end_ts: "2026-11-02T00:00:00Z",
    status: "ready",
    stats: {},
    ...sobrescreve,
  };
}

test("defaults vêm do contrato", () => {
  expect(hiperparametrosIniciais("lstm").units).toBe(64);
  expect(hiperparametrosIniciais("esn").units).toBe(500);
  expect(hiperparametrosIniciais("lstm").batch_size).toBe(32);
  expect(hiperparametrosIniciais("pls")).toEqual({ n_components: 3 });
  for (const metodo of ["pls", "esn", "lstm"] as const) {
    expect(Object.keys(hiperparametrosIniciais(metodo)), metodo).toEqual(
      Object.keys(SOFT_SENSOR_HYPERPARAMS[metodo]),
    );
  }
});

test("campo fora do limite devolve a mensagem com a faixa", () => {
  expect(problemaDoCampo("esn", "units", 600)).toBe("Deve estar entre 10 e 500");
  expect(problemaDoCampo("esn", "units", 9)).toBe("Deve estar entre 10 e 500");
  expect(problemaDoCampo("esn", "units", 10)).toBeNull();
  expect(problemaDoCampo("esn", "units", 500)).toBeNull();
  // vazio ou texto não numérico chega como NaN
  expect(problemaDoCampo("esn", "units", Number.NaN)).toBe("Deve estar entre 10 e 500");
});

test("campo gt 0 recusa o zero e aceita o que está logo acima; o teto é inclusivo", () => {
  // `sr` é `gt 0, le 2` no contrato (`exclusive_min`)
  expect(problemaDoCampo("esn", "sr", 0)).toBe("Deve estar entre 0 e 2");
  expect(problemaDoCampo("esn", "sr", 0.0001)).toBeNull();
  expect(problemaDoCampo("esn", "sr", 2)).toBeNull();
  expect(problemaDoCampo("esn", "sr", 2.1)).toBe("Deve estar entre 0 e 2");
  // `ridge` é `ge 0`: o zero vale
  expect(problemaDoCampo("esn", "ridge", 0)).toBeNull();
  // decimal em pt-BR (vírgula), como o resto da tela
  expect(problemaDoCampo("lstm", "lr", 0.5)).toBe("Deve estar entre 0 e 0,1");
});

test("campo de lista fechada só aceita as opções do contrato", () => {
  expect(problemaDoCampo("lstm", "batch_size", 32)).toBeNull();
  expect(problemaDoCampo("lstm", "batch_size", 33)).toBe("Deve ser um de 8, 16, 32, 64");
  expect(problemaDoCampo("esn", "inexistente", 1)).toBe("Parâmetro desconhecido");
});

test("validarHiperparametros converte o texto e separa os problemas por campo", () => {
  const textos = Object.fromEntries(
    Object.entries(hiperparametrosIniciais("esn")).map(([campo, valor]) => [campo, String(valor)]),
  );

  expect(validarHiperparametros("esn", textos)).toEqual({
    hiperparametros: hiperparametrosIniciais("esn"),
    problemas: {},
  });

  const ruins = validarHiperparametros("esn", { ...textos, units: "600", sr: "", seed: "abc" });
  expect(ruins.problemas).toEqual({
    units: "Deve estar entre 10 e 500",
    sr: "Deve estar entre 0 e 2",
    seed: "Deve estar entre 0 e 99.999",
  });
});

test("blocosCompativeis filtra por método, entradas e período", () => {
  const modelo = { method: "esn", n_inputs: 3, period_s: 60 };
  const compativel = bloco({ block_id: "ok", ts_seconds: 10 });
  const mesmoTs = bloco({ block_id: "igual", ts_seconds: 60 });
  const decimal = bloco({ block_id: "meio", ts_seconds: 0.5 });
  const outros = [
    bloco({ block_id: "lstm", method: "lstm" }),
    bloco({ block_id: "entradas", n_inputs: 4 }),
    bloco({ block_id: "naoMultiplo", ts_seconds: 7 }),
    bloco({ block_id: "tsMaior", ts_seconds: 120 }),
    bloco({ block_id: "tsZero", ts_seconds: 0 }),
  ];

  expect(blocosCompativeis(modelo, [compativel, ...outros, mesmoTs, decimal])).toEqual([
    compativel,
    mesmoTs,
    decimal,
  ]);
  expect(blocosCompativeis(modelo, [])).toEqual([]);
});

test("estadoDoModelo distingue em uso, aquecendo e aguardando", () => {
  const uso = (state: "active" | "candidate" | "pending", flow = "F1", block = "ss1") => ({
    flow_id: 1,
    flow_name: flow,
    block_id: block,
    state,
  });

  expect(estadoDoModelo({ in_use: [] })).toBe("—");
  expect(estadoDoModelo({ in_use: [uso("active")] })).toBe("em uso em F1 / ss1");
  expect(estadoDoModelo({ in_use: [uso("candidate")] })).toBe("aquecendo em F1 / ss1");
  expect(estadoDoModelo({ in_use: [uso("pending")] })).toBe("aguardando o runtime em F1 / ss1");
  // um modelo pode estar em mais de um bloco
  expect(estadoDoModelo({ in_use: [uso("active"), uso("candidate", "F2", "ss9")] })).toBe(
    "em uso em F1 / ss1; aquecendo em F2 / ss9",
  );
});

test("formatarAquecimento", () => {
  expect(formatarAquecimento(0)).toBe("nenhum");
  expect(formatarAquecimento(600)).toBe("10 min");
  expect(formatarAquecimento(6000)).toBe("1 h 40 min");
  expect(formatarAquecimento(3600)).toBe("1 h");
  expect(formatarAquecimento(90)).toBe("1 min 30 s");
  expect(formatarAquecimento(30)).toBe("30 s");
  // sem `warmup_steps` no meta do modelo: não inventa
  expect(formatarAquecimento(null)).toBe("—");
  expect(formatarAquecimento(undefined)).toBe("—");
});

test("aquecimentoDoModelo: um passo (PLS) é nenhum, mesmo com warmup_s = 1 x período", () => {
  // o PLS grava warmup_steps = 1, então a API devolve warmup_s = período (60 s aqui), nunca 0
  expect(aquecimentoDoModelo({ warmup_steps: 1, warmup_s: 60 })).toBe("nenhum");
  expect(aquecimentoDoModelo({ warmup_steps: 10, warmup_s: 600 })).toBe("10 min");
  expect(aquecimentoDoModelo({ warmup_steps: 100, warmup_s: 6000 })).toBe("1 h 40 min");
  expect(aquecimentoDoModelo({ warmup_steps: null, warmup_s: null })).toBe("—");
  expect(aquecimentoDoModelo({})).toBe("—");
});

test("formatarMetrica usa vírgula e não inventa número", () => {
  expect(formatarMetrica(0.84123)).toBe("0,8412");
  expect(formatarMetrica(123.456)).toBe("123,456");
  expect(formatarMetrica(undefined)).toBe("—");
  expect(formatarMetrica(Number.NaN)).toBe("—");
});

test("ativacaoRecente: janela de 60 s a partir da ativação deste cliente", () => {
  expect(ativacaoRecente(null, 1_000_000)).toBe(false);
  expect(ativacaoRecente(1_000_000, 1_000_000)).toBe(true);
  expect(ativacaoRecente(1_000_000, 1_059_999)).toBe(true);
  expect(ativacaoRecente(1_000_000, 1_060_000)).toBe(false);
});

test("precisaAcompanhar só com candidato aquecendo ou logo após a ativação deste cliente", () => {
  expect(precisaAcompanhar(undefined)).toBe(false);
  expect(precisaAcompanhar([])).toBe(false);
  // sem vínculo, ou pedido já atendido
  expect(precisaAcompanhar([bloco()])).toBe(false);
  expect(precisaAcompanhar([bloco({ desired_model_id: 5, active_model_id: 5 })])).toBe(false);
  // pedido que o runtime não atendeu e sem candidato (flow parado, import de projeto, deploy
  // que não carregou o modelo): estado que dura para sempre, então NÃO mantém o polling
  expect(precisaAcompanhar([bloco({ desired_model_id: 5 })])).toBe(false);
  expect(precisaAcompanhar([bloco({ desired_model_id: 5, active_model_id: 4 })])).toBe(false);
  // candidato aquecendo, mesmo com desired == active
  expect(
    precisaAcompanhar([bloco({ desired_model_id: 5, active_model_id: 5, candidate_model_id: 6 })]),
  ).toBe(true);
  expect(precisaAcompanhar([bloco({ candidate_model_id: 6 })])).toBe(true);
  // basta um bloco
  expect(precisaAcompanhar([bloco(), bloco({ candidate_model_id: 6 })])).toBe(true);
});

test("precisaAcompanhar: pedido sem candidato só acompanha dentro da janela da própria ativação", () => {
  const pendente = [bloco({ desired_model_id: 5 })];
  const ativadoEm = 1_000_000;

  // o runtime ainda vai pegar o `desired` e criar o candidato: 60 s de polling
  expect(precisaAcompanhar(pendente, ativadoEm, ativadoEm + 59_999)).toBe(true);
  expect(precisaAcompanhar(pendente, ativadoEm, ativadoEm + 60_000)).toBe(false);
  // sem ativação deste cliente (outra aba, import, deploy) não há janela
  expect(precisaAcompanhar(pendente, null, ativadoEm)).toBe(false);
});

test("temTrocaPendente: candidato nos modelos ou logo após a ativação deste cliente", () => {
  const uso = (state: "active" | "candidate" | "pending") => ({
    flow_id: 1,
    flow_name: "F1",
    block_id: "ss1",
    state,
  });

  expect(temTrocaPendente(undefined)).toBe(false);
  expect(temTrocaPendente([{ in_use: [] }, { in_use: [uso("active")] }])).toBe(false);
  expect(temTrocaPendente([{ in_use: [uso("active")] }, { in_use: [uso("candidate")] }])).toBe(true);
  // "aguardando o runtime" sozinho (sem candidato) não mantém o polling
  expect(temTrocaPendente([{ in_use: [uso("pending")] }])).toBe(false);
  // na janela de 60 s da própria ativação o pedido ainda é acompanhado
  expect(temTrocaPendente([{ in_use: [uso("pending")] }], 1_000_000, 1_059_999)).toBe(true);
  expect(temTrocaPendente([{ in_use: [uso("pending")] }], 1_000_000, 1_060_000)).toBe(false);
});

test("progressoDoTreino lê epoch/epochs; sem época a barra fica indeterminada", () => {
  expect(progressoDoTreino({ stage: "training", epoch: 3, epochs: 100 })).toEqual({
    feito: 3,
    total: 100,
  });
  // PLS e ESN não reportam época; a fila e a gravação também não
  expect(progressoDoTreino({ stage: "training" })).toBeNull();
  expect(progressoDoTreino({ stage: "saving" })).toBeNull();
  expect(progressoDoTreino({})).toBeNull();
  expect(progressoDoTreino({ epoch: "3", epochs: "100" })).toBeNull();
  expect(progressoDoTreino({ epoch: 0, epochs: 0 })).toBeNull();
  // o LSTM reporta 1..N no ajuste de 80% e de novo 1..N no reajuste de 100%: cada leitura é
  // independente, a época pode voltar para baixo uma vez e a barra só acompanha
  expect(progressoDoTreino({ epoch: 100, epochs: 100 })).toEqual({ feito: 100, total: 100 });
  expect(progressoDoTreino({ epoch: 1, epochs: 100 })).toEqual({ feito: 1, total: 100 });
  // a parada antecipada ou um relato fora de ordem não pode estourar o `max` do <progress>
  expect(progressoDoTreino({ epoch: 120, epochs: 100 })).toEqual({ feito: 100, total: 100 });
});

test("conjuntosCompativeis: mesmo pronto, variável, entradas na mesma ordem e período", () => {
  const base = conjunto({ id: 1 });
  const compativel = conjunto({ id: 2, name: "enxofre-b" });
  const todos = [
    base,
    compativel,
    conjunto({ id: 3, status: "collecting" }),
    conjunto({ id: 4, lab_variable_id: 8 }),
    conjunto({ id: 5, input_tag_ids: [10, 12, 11] }),
    conjunto({ id: 6, input_tag_ids: [10, 11] }),
    conjunto({ id: 7, period_s: 30 }),
  ];

  expect(conjuntosCompativeis(base, todos)).toEqual([compativel]);
});
