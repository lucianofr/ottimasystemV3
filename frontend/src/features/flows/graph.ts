import type { Edge, Node, XYPosition } from "@xyflow/react";

/**
 * Modelo do grafo do editor + as regras que o editor espelha do servidor.
 *
 * O servidor (`ottima_core/flowgraph.py`) é a fonte da verdade da validação (spec F3 §6.2):
 * aqui só vivem as três regras que o usuário sente na ponta do mouse — tipos de porta
 * (decisão A-5), ciclo (RF-302) e no máximo uma aresta por porta de entrada — mais a
 * aritmética de `exec_order` (ADR-024) e o aviso de inversão (RF-307).
 *
 * Regra dura da serialização: `data` carrega **apenas** as chaves que o servidor aceita
 * (`exec_order`, `label` e a config do tipo). Chave desconhecida dentro de `data` é 422; por
 * isso nenhum estado de interface pode morar ali.
 */

export const TIPOS_BLOCO = ["opc_read", "opc_write", "script", "tfs"] as const;
export type TipoBloco = (typeof TIPOS_BLOCO)[number];

/** Teto de portas do bloco Script (spec F3 §3.3). */
export const MAX_PORTAS_SCRIPT = 8;

export const ROTULO_BLOCO: Record<TipoBloco, string> = {
  opc_read: "Leitura OPC",
  opc_write: "Escrita OPC",
  script: "Script",
  tfs: "TFS",
};

export type TipoDadoTag = "float" | "int" | "bool";

/** `tag_id` das tags do projeto ativo, para o espelho de tipagem das portas. */
export type MapaTags = ReadonlyMap<number, TipoDadoTag>;

type DadosBase = { exec_order: number; label: string };

export type DadosTag = DadosBase & { tag_id: number | null };
export type DadosScript = DadosBase & { n_inputs: number; n_outputs: number; code: string };

export type ParamsSopdt = { K: number; tau1: number; tau2: number; theta: number };
export type ParamsIopdt = { Ki: number; theta: number };
export type TipoElemento = "sopdt" | "iopdt";

export type ElementoTfs =
  | { enabled: boolean; kind: "sopdt"; params: ParamsSopdt }
  | { enabled: boolean; kind: "iopdt"; params: ParamsIopdt };

/** `matrix[J][K]` é a contribuição de `uK` para `yJ` (spec F3 §3.4); sempre 2x2. */
export type LinhaTfs = [ElementoTfs, ElementoTfs];
export type MatrizTfs = [LinhaTfs, LinhaTfs];

export type DadosTfs = DadosBase & { matrix: MatrizTfs };

export type DadosBloco = DadosTag | DadosScript | DadosTfs;

/** `type` é opcional em `Node`; aqui ele é o discriminante e nunca falta. */
type Bloco<D extends Record<string, unknown>, T extends TipoBloco> = Node<D, T> & { type: T };

export type NoLeitura = Bloco<DadosTag, "opc_read">;
export type NoEscrita = Bloco<DadosTag, "opc_write">;
export type NoScript = Bloco<DadosScript, "script">;
export type NoTfs = Bloco<DadosTfs, "tfs">;

export type BlocoNode = NoLeitura | NoEscrita | NoScript | NoTfs;

/** Toda aresta do editor nasce de um par de handles resolvidos; `null` nunca chega ao save. */
export type BlocoEdge = Omit<Edge, "sourceHandle" | "targetHandle"> & {
  sourceHandle: string;
  targetHandle: string;
};

export type GrafoEditor = { nodes: BlocoNode[]; edges: BlocoEdge[] };

// --------------------------------------------------------------------------------------
// Portas
// --------------------------------------------------------------------------------------

/** Portas do Script: IN1..INn / OUT1..OUTn (GLOSSARY). */
export function portasScript(prefixo: "IN" | "OUT", quantidade: number): string[] {
  return Array.from({ length: quantidade }, (_, i) => `${prefixo}${String(i + 1)}`);
}

export const PORTAS_TFS_ENTRADA = ["u1", "u2"];
export const PORTAS_TFS_SAIDA = ["y1", "y2"];

export function handlesEntrada(no: BlocoNode): string[] {
  switch (no.type) {
    case "opc_write":
      return ["in"];
    case "script":
      return portasScript("IN", no.data.n_inputs);
    case "tfs":
      return [...PORTAS_TFS_ENTRADA];
    default:
      return [];
  }
}

export function handlesSaida(no: BlocoNode): string[] {
  switch (no.type) {
    case "opc_read":
      return ["out"];
    case "script":
      return portasScript("OUT", no.data.n_outputs);
    case "tfs":
      return [...PORTAS_TFS_SAIDA];
    default:
      return [];
  }
}

export type TipoPorta = "num" | "bool" | "bivalente" | "desconhecido";

const ROTULO_PORTA: Record<Exclude<TipoPorta, "desconhecido">, string> = {
  num: "numérica",
  bool: "booleana",
  bivalente: "bivalente",
};

/**
 * Tipo das portas do bloco (decisão A-5). Cada tipo tem um único sentido de porta, então um
 * valor serve os dois lados da aresta. `desconhecido` = Read/Write ainda sem tag: o contrato
 * manda permitir a ligação e deixar o 422 do save resolver, para não travar o fluxo natural
 * de "ligo primeiro, configuro depois".
 */
export function tipoPorta(no: BlocoNode, tags: MapaTags): TipoPorta {
  if (no.type === "script") return "bivalente";
  if (no.type === "tfs") return "num";
  if (no.data.tag_id === null) return "desconhecido";
  const dado = tags.get(no.data.tag_id);
  if (dado === undefined) return "desconhecido";
  return dado === "bool" ? "bool" : "num";
}

function rotuloDe(no: BlocoNode): string {
  return no.data.label.trim() || ROTULO_BLOCO[no.type];
}

// --------------------------------------------------------------------------------------
// Validação de conexão no arraste
// --------------------------------------------------------------------------------------

export type ConexaoPretendida = {
  source: string;
  target: string;
  sourceHandle: string | null;
  targetHandle: string | null;
};

/** Existe caminho `de` -> `ate` seguindo as arestas? Serve à detecção de ciclo. */
function alcanca(de: string, ate: string, edges: readonly BlocoEdge[]): boolean {
  const visitados = new Set<string>([de]);
  const fila: string[] = [de];
  while (fila.length > 0) {
    const atual = fila.shift();
    if (atual === undefined) break;
    if (atual === ate) return true;
    for (const aresta of edges) {
      if (aresta.source === atual && !visitados.has(aresta.target)) {
        visitados.add(aresta.target);
        fila.push(aresta.target);
      }
    }
  }
  return false;
}

/**
 * Motivo pt-BR da recusa, ou `null` se a conexão é aceitável para o editor.
 *
 * Espelho leve (spec F3 §6.2): integridade de tag, contiguidade de `exec_order` e entradas
 * obrigatórias continuam sendo do 422 do save.
 */
export function motivoRecusa(
  conexao: ConexaoPretendida,
  nodes: readonly BlocoNode[],
  edges: readonly BlocoEdge[],
  tags: MapaTags,
): string | null {
  const { source, target, sourceHandle, targetHandle } = conexao;
  if (sourceHandle === null || targetHandle === null) {
    return "Ligue uma porta de saída a uma porta de entrada.";
  }
  const origem = nodes.find((no) => no.id === source);
  const destino = nodes.find((no) => no.id === target);
  if (origem === undefined || destino === undefined) {
    return "Bloco de origem ou de destino não está mais no canvas.";
  }
  if (source === target) {
    return "Um bloco não pode alimentar a si mesmo: o fluxo de dados precisa ser acíclico.";
  }
  if (alcanca(target, source, edges)) {
    return (
      `Ligação recusada: fecharia um ciclo — '${rotuloDe(destino)}' já alimenta ` +
      `'${rotuloDe(origem)}'. O fluxo de dados precisa ser acíclico.`
    );
  }
  if (edges.some((aresta) => aresta.target === target && aresta.targetHandle === targetHandle)) {
    return (
      `A entrada '${targetHandle}' de '${rotuloDe(destino)}' já recebe uma ligação; ` +
      "cada porta de entrada aceita no máximo uma."
    );
  }
  const saida = tipoPorta(origem, tags);
  const entrada = tipoPorta(destino, tags);
  if (saida === "desconhecido" || entrada === "desconhecido") return null;
  if (saida === "bivalente" || entrada === "bivalente" || saida === entrada) return null;
  return (
    `A saída '${sourceHandle}' é ${ROTULO_PORTA[saida]} e a entrada '${targetHandle}' é ` +
    `${ROTULO_PORTA[entrada]}; só as portas do bloco Script são bivalentes.`
  );
}

/**
 * Aviso local de inversão (RF-307, não-bloqueante). O save também devolve os avisos do
 * servidor; este existe para o engenheiro ver a inversão no instante em que a cria.
 */
export function avisosInversao(nodes: readonly BlocoNode[], edges: readonly BlocoEdge[]): string[] {
  const porId = new Map(nodes.map((no) => [no.id, no]));
  const avisos: string[] = [];
  for (const aresta of edges) {
    const origem = porId.get(aresta.source);
    const destino = porId.get(aresta.target);
    if (origem === undefined || destino === undefined) continue;
    if (destino.data.exec_order < origem.data.exec_order) {
      avisos.push(
        `'${rotuloDe(destino)}' (exec_order ${String(destino.data.exec_order)}) consome a ` +
          `saída de '${rotuloDe(origem)}' (exec_order ${String(origem.data.exec_order)}); ` +
          "o valor usado será o da varredura anterior.",
      );
    }
  }
  return avisos;
}

// --------------------------------------------------------------------------------------
// exec_order (ADR-024)
// --------------------------------------------------------------------------------------

/** Menor inteiro livre. Com compactação no excluir o conjunto é sempre 1..N, mas o menor
 *  livre também é o comportamento correto ao abrir um grafo antigo com buracos. */
export function proximoExecOrder(nodes: readonly BlocoNode[]): number {
  const usados = new Set(nodes.map((no) => no.data.exec_order));
  let candidato = 1;
  while (usados.has(candidato)) candidato += 1;
  return candidato;
}

/** Atualiza campos comuns de `data`; id, posição e config seguem intactos (ADR-024). */
export function comDados(no: BlocoNode, mudanca: Partial<DadosBase>): BlocoNode {
  switch (no.type) {
    case "opc_read":
    case "opc_write":
      return { ...no, data: { ...no.data, ...mudanca } };
    case "script":
      return { ...no, data: { ...no.data, ...mudanca } };
    case "tfs":
      return { ...no, data: { ...no.data, ...mudanca } };
  }
}

/** Ordem vigente dos ids: por `exec_order`, empate pelo id para ser determinístico. */
function ordemVigente(nodes: readonly BlocoNode[]): string[] {
  return [...nodes]
    .sort((a, b) => a.data.exec_order - b.data.exec_order || a.id.localeCompare(b.id))
    .map((no) => no.id);
}

function renumerar(nodes: readonly BlocoNode[], ordenados: readonly string[]): BlocoNode[] {
  const posicao = new Map(ordenados.map((id, indice) => [id, indice + 1]));
  return nodes.map((no) => {
    const alvo = posicao.get(no.id);
    if (alvo === undefined || alvo === no.data.exec_order) return no;
    return comDados(no, { exec_order: alvo });
  });
}

/** Compactação automática ao excluir (ADR-024): o conjunto volta a ser contíguo 1..N. */
export function compactarExecOrder(nodes: readonly BlocoNode[]): BlocoNode[] {
  return renumerar(nodes, ordemVigente(nodes));
}

/**
 * Edição manual do `exec_order` no modal: o bloco é reinserido na posição pedida e a fila
 * inteira é renumerada 1..N. Reinserir (e não trocar de par) é o que o engenheiro espera de
 * "este bloco passa a rodar antes": os demais deslizam, ninguém é despejado para o fim.
 * Valor fora de 1..N é preso na faixa — contiguidade é invariante do ADR-024.
 */
export function definirExecOrder(
  nodes: readonly BlocoNode[],
  id: string,
  desejado: number,
): BlocoNode[] {
  const ordem = ordemVigente(nodes);
  const atual = ordem.indexOf(id);
  if (atual === -1) return [...nodes];
  const alvo = Math.min(Math.max(Math.trunc(desejado), 1), ordem.length) - 1;
  ordem.splice(atual, 1);
  ordem.splice(alvo, 0, id);
  return renumerar(nodes, ordem);
}

// --------------------------------------------------------------------------------------
// Criação de blocos
// --------------------------------------------------------------------------------------

export function paramsPadrao(kind: "sopdt"): ParamsSopdt;
export function paramsPadrao(kind: "iopdt"): ParamsIopdt;
export function paramsPadrao(kind: TipoElemento): ParamsSopdt | ParamsIopdt;
export function paramsPadrao(kind: TipoElemento): ParamsSopdt | ParamsIopdt {
  return kind === "sopdt" ? { K: 1, tau1: 1, tau2: 0, theta: 0 } : { Ki: 1, theta: 0 };
}

function elementoPadrao(): ElementoTfs {
  return { enabled: false, kind: "sopdt", params: paramsPadrao("sopdt") };
}

export function matrizPadrao(): MatrizTfs {
  return [
    [elementoPadrao(), elementoPadrao()],
    [elementoPadrao(), elementoPadrao()],
  ];
}

export function criarBloco(
  tipo: TipoBloco,
  id: string,
  position: XYPosition,
  exec_order: number,
): BlocoNode {
  switch (tipo) {
    case "opc_read":
      return { id, type: "opc_read", position, data: { exec_order, label: "", tag_id: null } };
    case "opc_write":
      return { id, type: "opc_write", position, data: { exec_order, label: "", tag_id: null } };
    case "script":
      return {
        id,
        type: "script",
        position,
        data: { exec_order, label: "", n_inputs: 1, n_outputs: 1, code: "OUT1 = IN1\n" },
      };
    case "tfs":
      return { id, type: "tfs", position, data: { exec_order, label: "", matrix: matrizPadrao() } };
  }
}

// --------------------------------------------------------------------------------------
// Serialização (contrato do `graph_json`)
// --------------------------------------------------------------------------------------

export type NoSerializado = {
  id: string;
  type: TipoBloco;
  position: { x: number; y: number };
  data: DadosBloco;
};

export type ArestaSerializada = {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
  targetHandle: string;
};

export type GraphJson = { nodes: NoSerializado[]; edges: ArestaSerializada[] };

/**
 * Emite exatamente o que o servidor aceita. As chaves que o React Flow pendura no topo do nó
 * (`selected`, `dragging`, `measured`) ficam de fora; `data` sai verbatim porque só carrega
 * chaves de contrato.
 */
export function paraGraphJson(nodes: readonly BlocoNode[], edges: readonly BlocoEdge[]): GraphJson {
  return {
    nodes: nodes.map((no) => ({
      id: no.id,
      type: no.type,
      position: { x: no.position.x, y: no.position.y },
      data: no.data,
    })),
    edges: edges.map((aresta) => ({
      id: aresta.id,
      source: aresta.source,
      target: aresta.target,
      sourceHandle: aresta.sourceHandle,
      targetHandle: aresta.targetHandle,
    })),
  };
}

function objeto(valor: unknown): Record<string, unknown> | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null;
}

function numero(valor: unknown, padrao: number): number {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : padrao;
}

function inteiro(valor: unknown, padrao: number, minimo: number, maximo: number): number {
  return Math.min(Math.max(Math.trunc(numero(valor, padrao)), minimo), maximo);
}

function texto(valor: unknown, padrao: string): string {
  return typeof valor === "string" ? valor : padrao;
}

function lerElemento(bruto: unknown): ElementoTfs {
  const cru = objeto(bruto);
  if (cru === null) return elementoPadrao();
  const enabled = cru.enabled === true;
  const params = objeto(cru.params) ?? {};
  if (cru.kind === "iopdt") {
    return {
      enabled,
      kind: "iopdt",
      params: { Ki: numero(params.Ki, 1), theta: numero(params.theta, 0) },
    };
  }
  return {
    enabled,
    kind: "sopdt",
    params: {
      K: numero(params.K, 1),
      tau1: numero(params.tau1, 0),
      tau2: numero(params.tau2, 0),
      theta: numero(params.theta, 0),
    },
  };
}

function lerMatriz(bruto: unknown): MatrizTfs {
  const linhas: unknown[] = Array.isArray(bruto) ? bruto : [];
  const linha = (j: number): LinhaTfs => {
    const bruta = linhas[j];
    const colunas: unknown[] = Array.isArray(bruta) ? bruta : [];
    return [lerElemento(colunas[0]), lerElemento(colunas[1])];
  };
  return [linha(0), linha(1)];
}

function lerNo(bruto: unknown, indice: number): BlocoNode | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  const tipo = TIPOS_BLOCO.find((candidato) => candidato === cru.type);
  if (id === "" || tipo === undefined) return null;

  const posicao = objeto(cru.position) ?? {};
  const position: XYPosition = { x: numero(posicao.x, 0), y: numero(posicao.y, 0) };
  const dados = objeto(cru.data) ?? {};
  const exec_order = inteiro(dados.exec_order, indice + 1, 1, Number.MAX_SAFE_INTEGER);
  const label = texto(dados.label, "");

  switch (tipo) {
    case "opc_read":
    case "opc_write": {
      const cruId = dados.tag_id;
      const tag_id = typeof cruId === "number" && Number.isInteger(cruId) ? cruId : null;
      return { id, type: tipo, position, data: { exec_order, label, tag_id } };
    }
    case "script":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          n_inputs: inteiro(dados.n_inputs, 0, 0, MAX_PORTAS_SCRIPT),
          n_outputs: inteiro(dados.n_outputs, 0, 0, MAX_PORTAS_SCRIPT),
          code: texto(dados.code, ""),
        },
      };
    case "tfs":
      return {
        id,
        type: tipo,
        position,
        data: { exec_order, label, matrix: lerMatriz(dados.matrix) },
      };
  }
}

function lerAresta(bruto: unknown): BlocoEdge | null {
  const cru = objeto(bruto);
  if (cru === null) return null;
  const id = texto(cru.id, "");
  const source = texto(cru.source, "");
  const target = texto(cru.target, "");
  const sourceHandle = texto(cru.sourceHandle, "");
  const targetHandle = texto(cru.targetHandle, "");
  if (id === "" || source === "" || target === "" || sourceHandle === "" || targetHandle === "") {
    return null;
  }
  return { id, source, target, sourceHandle, targetHandle };
}

/**
 * Lê o `graph_json` que veio do servidor. O tipo gerado do OpenAPI é um mapa opaco, então a
 * conversão acontece aqui, uma vez, em vez de espalhar `unknown` pelo editor. Nó ilegível é
 * descartado junto com as arestas que o citam — o editor não desenha meia aresta.
 */
export function deGraphJson(bruto: unknown): GrafoEditor {
  const cru = objeto(bruto) ?? {};
  const nodes = (Array.isArray(cru.nodes) ? cru.nodes : [])
    .map((no, indice) => lerNo(no, indice))
    .filter((no): no is BlocoNode => no !== null);
  const ids = new Set(nodes.map((no) => no.id));
  const edges = (Array.isArray(cru.edges) ? cru.edges : [])
    .map(lerAresta)
    .filter((aresta): aresta is BlocoEdge => aresta !== null)
    .filter((aresta) => ids.has(aresta.source) && ids.has(aresta.target));
  return { nodes, edges };
}
