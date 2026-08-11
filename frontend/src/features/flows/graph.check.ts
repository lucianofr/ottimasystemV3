import { expect, test } from "@playwright/test";

import {
  avisosInversao,
  compactarExecOrder,
  criarBloco,
  deGraphJson,
  definirExecOrder,
  euDaPortaDeEntrada,
  handlesEntrada,
  handlesSaida,
  matrizPadrao,
  motivoRecusa,
  paraGraphJson,
  podarArestasDoBloco,
  podarOutputEuScript,
  proximaPosicaoNaGrade,
  proximoExecOrder,
  tipoPorta,
  type BlocoEdge,
  type BlocoNode,
  type FaixaMpc,
  type MapaTags,
} from "./graph";

const POS = { x: 0, y: 0 };

/** Tags do projeto do flow, como o editor as monta a partir de `useTags`. */
const TAGS: MapaTags = new Map([
  [10, "float"],
  [11, "bool"],
  [20, "float"],
  [21, "bool"],
]);

function leitura(id: string, ordem: number, tag: number | null): BlocoNode {
  return { id, type: "opc_read", position: POS, data: { exec_order: ordem, label: "", tag_id: tag } };
}

function escrita(id: string, ordem: number, tag: number | null): BlocoNode {
  return {
    id,
    type: "opc_write",
    position: POS,
    data: { exec_order: ordem, label: "", tag_id: tag },
  };
}

function script(id: string, ordem: number, entradas = 1, saidas = 1): BlocoNode {
  return {
    id,
    type: "script",
    position: POS,
    data: { exec_order: ordem, label: "", n_inputs: entradas, n_outputs: saidas, code: "", output_eu: {} },
  };
}

function tfs(id: string, ordem: number): BlocoNode {
  return criarBloco("tfs", id, POS, ordem);
}

/** Nó MPC com config vazio-mas-válido (criarBloco); `overrides` substitui `variables`/`name`
 *  etc. para os testes de porta dinâmica e round-trip. */
function mpc(id: string, ordem: number, overrides: Partial<BlocoNode["data"]> = {}): BlocoNode {
  const base = criarBloco("mpc", id, POS, ordem);
  if (base.type !== "mpc") throw new Error("tipo preservado");
  return { ...base, data: { ...base.data, ...overrides } };
}

function variavelMv(id: string, name: string, eu: string, comPid = false) {
  return {
    id,
    name,
    eu,
    limits: { min: 0, max: 100 },
    du_max: 5,
    du_min: 0,
    move_weight: 1,
    initial_value: 0,
    operating_point: 0,
    readback_tag_id: null,
    pid: comPid
      ? {
          write_tag_id: 12,
          target_mode: "rcas" as const,
          mode_cmd_tag_id: 13,
          mode_read_tag_id: 14,
          readback_tag_id: 15,
          mode_values: { auto: 1, target: 3 },
        }
      : null,
    objective: "none" as const,
    psv: null,
  };
}

function variavelCv(id: string, name: string, eu: string) {
  return {
    id,
    name,
    eu,
    kind: "selfreg" as const,
    tss: 600,
    weight: 1,
    sp_limits: { min: 80, max: 120 },
    objective: "none" as const,
  };
}

function variavelRestricao(id: string, name: string, eu: string) {
  return {
    id,
    name,
    eu,
    kind: "integrating" as const,
    tss: 900,
    range: { low: 20, high: 80 },
    priority: 1,
    objective: "none" as const,
  };
}

function variavelDv(id: string, name: string, eu: string, range: FaixaMpc | null = null) {
  return { id, name, eu, range, operating_point: 0 };
}

function aresta(
  id: string,
  source: string,
  sourceHandle: string,
  target: string,
  targetHandle: string,
): BlocoEdge {
  return { id, source, sourceHandle, target, targetHandle };
}

function ordens(nodes: readonly BlocoNode[]): Record<string, number> {
  return Object.fromEntries(nodes.map((no) => [no.id, no.data.exec_order]));
}

// --------------------------------------------------------------------------------------
// Portas
// --------------------------------------------------------------------------------------

test("os handles de cada tipo são exatamente os que o servidor reconhece", () => {
  expect(handlesSaida(leitura("r", 1, 10))).toEqual(["out"]);
  expect(handlesEntrada(leitura("r", 1, 10))).toEqual([]);
  expect(handlesEntrada(escrita("w", 1, 20))).toEqual(["in"]);
  expect(handlesSaida(escrita("w", 1, 20))).toEqual([]);
  expect(handlesEntrada(tfs("t", 1))).toEqual(["u1", "u2"]);
  expect(handlesSaida(tfs("t", 1))).toEqual(["y1", "y2"]);
});

test("criarBloco('mpc', ...) nasce com config vazio e sem portas (spec F4 §2.1)", () => {
  const no = mpc("m", 1);
  if (no.type !== "mpc") throw new Error("tipo preservado");
  expect(no.data).toEqual({
    exec_order: 1,
    label: "",
    name: "",
    multiplier: 1,
    variables: { mvs: [], cvs: [], constraints: [], dvs: [] },
    models: {},
  });
  expect(handlesEntrada(no)).toEqual([]);
  expect(handlesSaida(no)).toEqual([]);
});

test("portas do MPC são dinâmicas do config: entradas CV+Restrição+DV, saída MV, na ordem (decisão A-10)", () => {
  const no = mpc("m", 1, {
    variables: {
      mvs: [variavelMv("mv_1", "Vazão de refluxo", "m3/h")],
      cvs: [variavelCv("cv_1", "Temperatura de topo", "C")],
      constraints: [variavelRestricao("co_1", "Nível do vaso", "%")],
      dvs: [variavelDv("dv_1", "Vazão de carga", "m3/h")],
    },
  });
  expect(handlesEntrada(no)).toEqual(["cv_1", "co_1", "dv_1"]);
  expect(handlesSaida(no)).toEqual(["mv_1"]);
});

test("tipo da porta do MPC é sempre numérico (spec F4 §2.1-5)", () => {
  expect(tipoPorta(mpc("m", 1), TAGS)).toBe("num");
});

test("as portas do Script acompanham n_inputs/n_outputs, inclusive em zero", () => {
  expect(handlesEntrada(script("s", 1, 3, 2))).toEqual(["IN1", "IN2", "IN3"]);
  expect(handlesSaida(script("s", 1, 3, 2))).toEqual(["OUT1", "OUT2"]);
  expect(handlesEntrada(script("s", 1, 0, 0))).toEqual([]);
  expect(handlesSaida(script("s", 1, 0, 0))).toEqual([]);
});

test("tipo da porta herda a tag; sem tag configurada o tipo é desconhecido", () => {
  expect(tipoPorta(leitura("r", 1, 10), TAGS)).toBe("num");
  expect(tipoPorta(leitura("r", 1, 11), TAGS)).toBe("bool");
  expect(tipoPorta(leitura("r", 1, null), TAGS)).toBe("desconhecido");
  // tag de outro projeto (fora do mapa) também é desconhecida: quem reprova é o save
  expect(tipoPorta(leitura("r", 1, 999), TAGS)).toBe("desconhecido");
  expect(tipoPorta(script("s", 1), TAGS)).toBe("bivalente");
  expect(tipoPorta(tfs("t", 1), TAGS)).toBe("num");
});

// --------------------------------------------------------------------------------------
// Validação de conexão no arraste (decisão A-5, RF-302)
// --------------------------------------------------------------------------------------

test("saída booleana em entrada numérica é recusada com o motivo em pt-BR", () => {
  const nodes = [leitura("r", 1, 11), tfs("t", 2)];
  const motivo = motivoRecusa(
    { source: "r", sourceHandle: "out", target: "t", targetHandle: "u1" },
    nodes,
    [],
    TAGS,
  );
  expect(motivo).toContain("booleana");
  expect(motivo).toContain("numérica");
  expect(motivo).toContain("bivalentes");
});

test("tipos iguais passam e as portas do Script aceitam os dois lados", () => {
  const nodes = [leitura("num", 1, 10), leitura("bool", 2, 11), script("s", 3), escrita("w", 4, 21), tfs("t", 5)];
  const liga = (source: string, sourceHandle: string, target: string, targetHandle: string) =>
    motivoRecusa({ source, sourceHandle, target, targetHandle }, nodes, [], TAGS);

  expect(liga("num", "out", "t", "u1")).toBeNull();
  expect(liga("bool", "out", "s", "IN1")).toBeNull(); // bivalente do lado da entrada
  expect(liga("s", "OUT1", "w", "in")).toBeNull(); // bivalente do lado da saída (tag bool)
  expect(liga("t", "y1", "s", "IN1")).toBeNull();
});

test("bloco sem tag configurada não trava a ligação: o 422 do save resolve", () => {
  const nodes = [leitura("r", 1, null), tfs("t", 2)];
  expect(
    motivoRecusa({ source: "r", sourceHandle: "out", target: "t", targetHandle: "u1" }, nodes, [], TAGS),
  ).toBeNull();
});

test("ciclo é recusado, direto ou por caminho longo", () => {
  const nodes = [script("a", 1), script("b", 2), script("c", 3, 2, 1)];
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1"), aresta("e2", "b", "OUT1", "c", "IN1")];

  expect(
    motivoRecusa({ source: "c", sourceHandle: "OUT1", target: "a", targetHandle: "IN1" }, nodes, edges, TAGS),
  ).toContain("ciclo");
  expect(
    motivoRecusa({ source: "a", sourceHandle: "OUT1", target: "a", targetHandle: "IN1" }, nodes, edges, TAGS),
  ).toContain("a si mesmo");
  // o sentido que não fecha ciclo segue livre (IN2 de 'c' ainda está vaga)
  expect(
    motivoRecusa({ source: "a", sourceHandle: "OUT1", target: "c", targetHandle: "IN2" }, nodes, edges, TAGS),
  ).toBeNull();
});

test("porta de entrada aceita no máximo uma aresta; saída pode alimentar várias", () => {
  const nodes = [script("a", 1, 1, 2), script("b", 2, 2, 1), script("c", 3, 1, 1)];
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1")];

  expect(
    motivoRecusa({ source: "c", sourceHandle: "OUT1", target: "b", targetHandle: "IN1" }, nodes, edges, TAGS),
  ).toContain("no máximo uma");
  // outra entrada do mesmo bloco continua livre
  expect(
    motivoRecusa({ source: "c", sourceHandle: "OUT1", target: "b", targetHandle: "IN2" }, nodes, edges, TAGS),
  ).toBeNull();
  // a mesma saída alimentando um segundo destino é legítima (fan-out)
  expect(
    motivoRecusa({ source: "a", sourceHandle: "OUT1", target: "c", targetHandle: "IN1" }, nodes, edges, TAGS),
  ).toBeNull();
});

// --------------------------------------------------------------------------------------
// Inserção em grade por clique na paleta (débito m4-b, plano F4a)
// --------------------------------------------------------------------------------------

function noEm(id: string, posicao: { x: number; y: number }): BlocoNode {
  const no = script(id, 1);
  no.position = posicao;
  return no;
}

test("grade vazia começa no slot da própria âncora", () => {
  expect(proximaPosicaoNaGrade([], { x: 100, y: 50 })).toEqual({ x: 100, y: 50 });
});

test("grade contígua emenda no próximo slot livre", () => {
  const ancora = { x: 0, y: 0 };
  const nodes = [noEm("a", { x: 0, y: 0 }), noEm("b", { x: 250, y: 0 })];
  expect(proximaPosicaoNaGrade(nodes, ancora)).toEqual({ x: 500, y: 0 });
});

test("buraco no meio da grade (nó removido) tampa antes de avançar para o fim", () => {
  const ancora = { x: 0, y: 0 };
  // slot 1 (x=250) ficou livre porque o nó que ali estava foi excluído
  const nodes = [noEm("a", { x: 0, y: 0 }), noEm("c", { x: 500, y: 0 })];
  expect(proximaPosicaoNaGrade(nodes, ancora)).toEqual({ x: 250, y: 0 });
});

test("a quinta inserção quebra linha: volta para a coluna 0 na linha seguinte", () => {
  const ancora = { x: 0, y: 0 };
  const nodes = [0, 1, 2, 3].map((i) => noEm(`n${String(i)}`, { x: i * 250, y: 0 }));
  expect(proximaPosicaoNaGrade(nodes, ancora)).toEqual({ x: 0, y: 170 });
});

test("âncora fora da origem desloca a grade inteira, sem mudar o passo", () => {
  const ancora = { x: 40, y: 40 };
  const nodes = [noEm("a", { x: 40, y: 40 })];
  expect(proximaPosicaoNaGrade(nodes, ancora)).toEqual({ x: 290, y: 40 });
});

// --------------------------------------------------------------------------------------
// exec_order (ADR-024)
// --------------------------------------------------------------------------------------

test("próximo exec_order livre: começa em 1, segue N+1 e tampa buraco", () => {
  expect(proximoExecOrder([])).toBe(1);
  expect(proximoExecOrder([script("a", 1), script("b", 2)])).toBe(3);
  expect(proximoExecOrder([script("a", 1), script("b", 3)])).toBe(2);
});

test("excluir compacta para 1..N mantendo a ordem relativa", () => {
  const restantes = [script("a", 1), script("c", 3), script("d", 5)];
  expect(ordens(compactarExecOrder(restantes))).toEqual({ a: 1, c: 2, d: 3 });
});

test("compactar não altera id, posição nem config do bloco", () => {
  const antes = criarBloco("script", "s", { x: 120, y: 40 }, 7);
  const [depois] = compactarExecOrder([antes]);
  expect(depois.id).toBe("s");
  expect(depois.position).toEqual({ x: 120, y: 40 });
  expect(depois.data.exec_order).toBe(1);
  if (depois.type !== "script") throw new Error("tipo preservado");
  expect(depois.data.code).toBe("OUT1 = IN1\n");
  expect(depois.data.n_inputs).toBe(1);
});

test("edição manual reinsere o bloco na posição pedida e renumera a fila", () => {
  const nodes = [script("a", 1), script("b", 2), script("c", 3), script("d", 4)];
  // "d passa a rodar primeiro": os demais deslizam, ninguém vai para o fim
  expect(ordens(definirExecOrder(nodes, "d", 1))).toEqual({ d: 1, a: 2, b: 3, c: 4 });
  // e o caminho de volta
  expect(ordens(definirExecOrder(nodes, "a", 4))).toEqual({ b: 1, c: 2, d: 3, a: 4 });
});

test("exec_order manual fora de 1..N é preso na faixa, nunca quebra a contiguidade", () => {
  const nodes = [script("a", 1), script("b", 2), script("c", 3)];
  expect(ordens(definirExecOrder(nodes, "c", 0))).toEqual({ c: 1, a: 2, b: 3 });
  expect(ordens(definirExecOrder(nodes, "a", 99))).toEqual({ b: 1, c: 2, a: 3 });
});

// --------------------------------------------------------------------------------------
// Aviso de inversão (RF-307)
// --------------------------------------------------------------------------------------

test("aresta invertida avisa; aresta na ordem normal não", () => {
  const nodes = [script("produtor", 2), script("consumidor", 1)];
  const invertida = avisosInversao(nodes, [aresta("e1", "produtor", "OUT1", "consumidor", "IN1")]);
  expect(invertida).toHaveLength(1);
  expect(invertida[0]).toContain("varredura anterior");

  const normal = [script("produtor", 1), script("consumidor", 2)];
  expect(avisosInversao(normal, [aresta("e1", "produtor", "OUT1", "consumidor", "IN1")])).toEqual([]);
});

test("o aviso usa o rótulo do bloco quando ele existe", () => {
  const produtor = script("p", 2);
  const consumidor = script("c", 1);
  produtor.data.label = "Vazão bruta";
  const avisos = avisosInversao(
    [produtor, consumidor],
    [aresta("e1", "p", "OUT1", "c", "IN1")],
  );
  expect(avisos[0]).toContain("Vazão bruta");
  expect(avisos[0]).toContain("Script"); // consumidor sem rótulo cai no nome do tipo
});

// --------------------------------------------------------------------------------------
// Serialização — o contrato duro (chave desconhecida em `data` é 422)
// --------------------------------------------------------------------------------------

test("data sai com exatamente as chaves do contrato, uma lista por tipo", () => {
  const nodes: BlocoNode[] = [
    criarBloco("opc_read", "r", POS, 1),
    criarBloco("opc_write", "w", POS, 2),
    criarBloco("script", "s", POS, 3),
    criarBloco("tfs", "t", POS, 4),
    criarBloco("mpc", "m", POS, 5),
  ];
  const chaves = paraGraphJson(nodes, []).nodes.map((no) => Object.keys(no.data).sort());
  expect(chaves).toEqual([
    ["exec_order", "label", "tag_id"],
    ["exec_order", "label", "tag_id"],
    ["code", "exec_order", "label", "n_inputs", "n_outputs", "output_eu"],
    ["exec_order", "label", "matrix", "output_eu"],
    ["exec_order", "label", "models", "multiplier", "name", "variables"],
  ]);
});

test("estado de interface do React Flow no topo do nó não vai para o graph_json", () => {
  const no: BlocoNode = { ...criarBloco("opc_read", "r", { x: 5, y: 6 }, 1), selected: true, dragging: true, measured: { width: 220, height: 96 } };
  const emitido = paraGraphJson([no], []).nodes[0];
  expect(Object.keys(emitido).sort()).toEqual(["data", "id", "position", "type"]);
  expect(emitido.position).toEqual({ x: 5, y: 6 });
});

test("aresta sai em camelCase, sem os campos de desenho do React Flow", () => {
  const emitida = paraGraphJson([], [{ ...aresta("e1", "r", "out", "t", "u1"), selected: true, animated: true }]).edges[0];
  expect(emitida).toEqual({ id: "e1", source: "r", sourceHandle: "out", target: "t", targetHandle: "u1" });
});

test("o elemento TFS carrega só os params do seu kind", () => {
  const no = criarBloco("tfs", "t", POS, 1);
  if (no.type !== "tfs") throw new Error("tipo preservado");
  no.data.matrix[0][1] = { enabled: true, kind: "iopdt", params: { Ki: 0.4, theta: 2 } };
  const dados = paraGraphJson([no], []).nodes[0].data;
  if (!("matrix" in dados)) throw new Error("matriz emitida");
  expect(Object.keys(dados.matrix[0][1].params).sort()).toEqual(["Ki", "theta"]);
  expect(Object.keys(dados.matrix[0][0].params).sort()).toEqual(["K", "tau1", "tau2", "theta"]);
  expect(dados.matrix).toHaveLength(2);
  expect(dados.matrix[1]).toHaveLength(2);
});

// --------------------------------------------------------------------------------------
// Leitura do graph_json do servidor
// --------------------------------------------------------------------------------------

test("ida e volta pelo graph_json preserva o grafo", () => {
  const nodes: BlocoNode[] = [
    {
      id: "r",
      type: "opc_read",
      position: { x: 10, y: 20 },
      data: { exec_order: 1, label: "PV", tag_id: 10 },
    },
    criarBloco("tfs", "t", { x: 300, y: 20 }, 2),
  ];
  const edges = [aresta("e1", "r", "out", "t", "u1")];
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson(nodes, edges))));
  expect(volta.nodes).toEqual(nodes);
  expect(volta.edges).toEqual(edges);
});

test("ida e volta pelo graph_json preserva output_eu do Script e do TFS (spec §4.1)", () => {
  const nodes: BlocoNode[] = [
    {
      id: "s",
      type: "script",
      position: POS,
      data: { exec_order: 1, label: "", n_inputs: 1, n_outputs: 2, code: "", output_eu: { OUT1: "t/h" } },
    },
    {
      id: "t",
      type: "tfs",
      position: { x: 300, y: 20 },
      data: { exec_order: 2, label: "", matrix: matrizPadrao(), output_eu: { y1: "C" } },
    },
  ];
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson(nodes, []))));
  expect(volta.nodes).toEqual(nodes);
});

test("nó Script/TFS salvo antes da F6, sem output_eu, carrega com {} (compatibilidade retroativa)", () => {
  const grafo = deGraphJson({
    nodes: [
      {
        id: "s",
        type: "script",
        position: POS,
        data: { exec_order: 1, label: "", n_inputs: 1, n_outputs: 1, code: "" },
      },
      { id: "t", type: "tfs", position: POS, data: { exec_order: 2, label: "", matrix: matrizPadrao() } },
    ],
    edges: [],
  });
  const s = grafo.nodes.find((no) => no.id === "s");
  const t = grafo.nodes.find((no) => no.id === "t");
  if (s?.type !== "script" || t?.type !== "tfs") throw new Error("tipos preservados");
  expect(s.data.output_eu).toEqual({});
  expect(t.data.output_eu).toEqual({});
});

test("ida e volta pelo graph_json preserva o nó mpc com config completo (mvs com pid, cvs, constraints, dvs, models)", () => {
  const no = mpc("m", 1, {
    name: "MPC da coluna",
    multiplier: 5,
    variables: {
      mvs: [variavelMv("mv_x7k2", "Vazão de refluxo", "m3/h", true)],
      cvs: [variavelCv("cv_a1b2", "Temperatura de topo", "C")],
      constraints: [variavelRestricao("co_c3d4", "Nível do vaso", "%")],
      dvs: [variavelDv("dv_e5f6", "Vazão de carga", "m3/h")],
    },
    models: {
      cv_a1b2: {
        mv_x7k2: { enabled: true, params: { K: 1.2, tau1: 120, tau2: 30, theta: 15 } },
      },
      co_c3d4: {
        mv_x7k2: { enabled: false, params: { Ki: 0.4, theta: 2 } },
      },
    },
  });
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson([no], []))));
  expect(volta.nodes).toEqual([no]);
});

test("nó mpc salvo antes da feature, sem objective/psv, carrega com defaults retrocompat (ADR-027 §9)", () => {
  const grafo = deGraphJson({
    nodes: [
      {
        id: "m",
        type: "mpc",
        position: POS,
        data: {
          exec_order: 1,
          label: "",
          name: "MPC antigo",
          multiplier: 5,
          variables: {
            mvs: [
              {
                id: "mv_x7k2",
                name: "Vazão de refluxo",
                eu: "m3/h",
                limits: { min: 0, max: 100 },
                du_max: 5,
                initial_value: 0,
                pid: null,
              },
            ],
            cvs: [
              {
                id: "cv_a1b2",
                name: "Temperatura de topo",
                eu: "C",
                kind: "selfreg",
                tss: 600,
                weight: 1,
                sp_limits: { min: 80, max: 120 },
              },
            ],
            constraints: [
              {
                id: "co_c3d4",
                name: "Nível do vaso",
                eu: "%",
                kind: "integrating",
                tss: 900,
                range: { low: 20, high: 80 },
                priority: 1,
              },
            ],
            dvs: [],
          },
          models: {},
        },
      },
    ],
    edges: [],
  });
  const no = grafo.nodes[0];
  if (no?.type !== "mpc") throw new Error("tipo preservado");
  expect(no.data.variables.mvs[0].objective).toBe("none");
  expect(no.data.variables.mvs[0].psv).toBeNull();
  expect(no.data.variables.cvs[0].objective).toBe("none");
  expect(no.data.variables.constraints[0].objective).toBe("none");
});

test("ida e volta preserva objective/psv configurados nas variáveis do mpc", () => {
  const no = mpc("m", 1, {
    name: "MPC otimizado",
    multiplier: 5,
    variables: {
      mvs: [{ ...variavelMv("mv_x7k2", "Vazão", "m3/h"), objective: "psv" as const, psv: 42 }],
      cvs: [{ ...variavelCv("cv_a1b2", "Temperatura", "C"), objective: "target" as const }],
      constraints: [
        { ...variavelRestricao("co_c3d4", "Nível", "%"), objective: "minimize" as const, kind: "selfreg" as const },
      ],
      dvs: [],
    },
    models: {},
  });
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson([no], []))));
  expect(volta.nodes).toEqual([no]);
});

test("grafo vazio do flow recém-criado abre sem nó nem aresta", () => {
  expect(deGraphJson({ nodes: [], edges: [] })).toEqual({ nodes: [], edges: [] });
  expect(deGraphJson(null)).toEqual({ nodes: [], edges: [] });
});

test("nó de tipo desconhecido é descartado junto com as arestas que o citam", () => {
  const grafo = deGraphJson({
    nodes: [
      { id: "m", type: "invalido", position: { x: 0, y: 0 }, data: { exec_order: 1 } },
      { id: "s", type: "script", position: { x: 0, y: 0 }, data: { exec_order: 2, n_inputs: 1, n_outputs: 1, code: "" } },
    ],
    edges: [
      { id: "e1", source: "m", target: "s", sourceHandle: "out", targetHandle: "IN1" },
      { id: "e2", source: "s", target: "s", sourceHandle: "OUT1", targetHandle: "IN1" },
    ],
  });
  expect(grafo.nodes.map((no) => no.id)).toEqual(["s"]);
  expect(grafo.edges.map((a) => a.id)).toEqual(["e2"]);
});

// --------------------------------------------------------------------------------------
// Poda de arestas ao reconfigurar o bloco
// --------------------------------------------------------------------------------------

test("encolher o Script derruba as arestas das portas que sumiram e mantém as que ficaram", () => {
  const edges = [
    aresta("e1", "a", "OUT1", "s", "IN1"),
    aresta("e2", "b", "OUT1", "s", "IN2"),
    aresta("e3", "c", "OUT1", "s", "IN3"),
  ];
  const encolhido = script("s", 1, 1, 1);
  expect(podarArestasDoBloco(edges, encolhido).map((a) => a.id)).toEqual(["e1"]);
});

test("reduzir n_outputs derruba as arestas que saíam das portas removidas", () => {
  const edges = [
    aresta("e1", "s", "OUT1", "w1", "in"),
    aresta("e2", "s", "OUT2", "w2", "in"),
  ];
  expect(podarArestasDoBloco(edges, script("s", 1, 1, 1)).map((a) => a.id)).toEqual(["e1"]);
});

test("arestas que não tocam o bloco reconfigurado passam intactas", () => {
  const edges = [
    aresta("e1", "x", "out", "y", "u1"),
    aresta("e2", "z", "OUT1", "s", "IN2"),
  ];
  const podadas = podarArestasDoBloco(edges, script("s", 1, 1, 1));
  expect(podadas.map((a) => a.id)).toEqual(["e1"]);
  expect(podadas[0]).toBe(edges[0]);
});

test("reconfigurar sem mexer nas portas não derruba nada", () => {
  const edges = [aresta("e1", "r", "out", "t", "u1"), aresta("e2", "t", "y1", "w", "in")];
  expect(podarArestasDoBloco(edges, tfs("t", 1))).toEqual(edges);
  expect(podarArestasDoBloco(edges, escrita("w", 2, 42))).toEqual(edges);
  expect(podarArestasDoBloco(edges, leitura("r", 3, 41))).toEqual(edges);
});

// --------------------------------------------------------------------------------------
// Poda de output_eu ao reduzir n_outputs (spec §4.1-6)
// --------------------------------------------------------------------------------------

test("reduzir n_outputs de 3 para 2 descarta a EU de OUT3 (servidor recusaria com 422)", () => {
  expect(podarOutputEuScript({ OUT1: "t/h", OUT2: "bar", OUT3: "C" }, 2)).toEqual({
    OUT1: "t/h",
    OUT2: "bar",
  });
});

test("aumentar n_outputs preserva as EUs existentes sem inventar a da porta nova", () => {
  expect(podarOutputEuScript({ OUT1: "t/h" }, 3)).toEqual({ OUT1: "t/h" });
});

test("zerar n_outputs descarta toda EU do Script", () => {
  expect(podarOutputEuScript({ OUT1: "t/h", OUT2: "bar" }, 0)).toEqual({});
});

// --------------------------------------------------------------------------------------
// EU herdada por porta de entrada (spec §4.1-5, tarefa 5.2)
// --------------------------------------------------------------------------------------

test("entrada ligada à saída com EU declarada herda a EU da origem", () => {
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1")];
  const output_eu_por_no = new Map([["a", { OUT1: "t/h" }]]);
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "b", "IN1")).toBe("t/h");
});

test("entrada solta (sem aresta chegando) não herda nada", () => {
  expect(euDaPortaDeEntrada([], new Map(), "b", "IN1")).toBeNull();
});

test("origem sem EU declarada para a porta (chave ausente ou vazia) devolve null", () => {
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1"), aresta("e2", "c", "OUT2", "d", "IN1")];
  const output_eu_por_no = new Map<string, Record<string, string>>([
    ["a", {}], // Script sem nenhuma EU declarada
    ["c", { OUT2: "" }], // porta com EU explicitamente vazia (mesmo default de Tag.eu)
  ]);
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "b", "IN1")).toBeNull();
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "d", "IN1")).toBeNull();
});

test("resolve só um nível: EU atravessando um Script intermediário sem EU própria não propaga (spec §4.1-6)", () => {
  // a(OUT1 = "t/h") -> b(IN1 herda "t/h", mas o OUT1 de b não declara nada) -> c(IN1)
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1"), aresta("e2", "b", "OUT1", "c", "IN1")];
  const output_eu_por_no = new Map<string, Record<string, string>>([
    ["a", { OUT1: "t/h" }],
    ["b", {}], // b não repete a EU herdada na própria saída — §4.1-6, sem propagação automática
  ]);
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "b", "IN1")).toBe("t/h");
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "c", "IN1")).toBeNull();
});

test("resolve pela combinação exata nó+handle: outra entrada do mesmo nó, ou o mesmo handle de outro nó, não interferem", () => {
  const edges = [aresta("e1", "a", "OUT1", "b", "IN1"), aresta("e2", "a", "OUT2", "b", "IN2")];
  const output_eu_por_no = new Map([["a", { OUT1: "t/h", OUT2: "bar" }]]);
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "b", "IN1")).toBe("t/h");
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "b", "IN2")).toBe("bar");
  expect(euDaPortaDeEntrada(edges, output_eu_por_no, "z", "IN1")).toBeNull();
});

// --------------------------------------------------------------------------------------
// range opcional da DV (spec §4.2, tarefa 5.3) — VariavelDv.range: FaixaMpc | null
// --------------------------------------------------------------------------------------

test("ida e volta pelo graph_json preserva o range da DV quando declarado", () => {
  const no = mpc("m", 1, {
    variables: {
      mvs: [],
      cvs: [],
      constraints: [],
      dvs: [variavelDv("dv_1", "Vazão de carga", "m3/h", { low: 0, high: 10 })],
    },
  });
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson([no], []))));
  expect(volta.nodes).toEqual([no]);
});

test("DV sem range fica com null explícito na ida e volta (padrão de DV nova)", () => {
  const no = mpc("m", 1, {
    variables: { mvs: [], cvs: [], constraints: [], dvs: [variavelDv("dv_1", "Vazão de carga", "m3/h")] },
  });
  const volta = deGraphJson(JSON.parse(JSON.stringify(paraGraphJson([no], []))));
  if (volta.nodes[0]?.type !== "mpc") throw new Error("tipo preservado");
  expect(volta.nodes[0].data.variables.dvs).toEqual([
    { id: "dv_1", name: "Vazão de carga", eu: "m3/h", range: null, operating_point: 0 },
  ]);
});

test("DV salva antes da F6, sem a chave range, carrega com null (compatibilidade retroativa)", () => {
  const grafo = deGraphJson({
    nodes: [
      {
        id: "m",
        type: "mpc",
        position: POS,
        data: {
          exec_order: 1,
          label: "",
          name: "",
          multiplier: 1,
          variables: {
            mvs: [],
            cvs: [],
            constraints: [],
            dvs: [{ id: "dv_1", name: "Vazão de carga", eu: "m3/h" }],
          },
          models: {},
        },
      },
    ],
    edges: [],
  });
  const no = grafo.nodes.find((n) => n.id === "m");
  if (no?.type !== "mpc") throw new Error("tipo preservado");
  expect(no.data.variables.dvs).toEqual([
    { id: "dv_1", name: "Vazão de carga", eu: "m3/h", range: null, operating_point: 0 },
  ]);
});
