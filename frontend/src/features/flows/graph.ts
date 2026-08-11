import type { Edge, Node, XYPosition } from "@xyflow/react";
import {
  PORT_CONTRACTS,
  type ContratoPortaDinamica,
  type DirecaoPorta,
  type RegraPortaDinamica,
} from "../../lib/contracts.gen";
import { lerModelosMpc, lerVariaveisMpc } from "./mpc/graphMpc";

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

export const TIPOS_BLOCO = [
  "opc_read",
  "opc_write",
  "script",
  "first_order",
  "kalman",
  "tfs",
  "mpc",
] as const;
export type TipoBloco = (typeof TIPOS_BLOCO)[number];

function tetoDoContrato(regra: RegraPortaDinamica): number {
  if (regra.max === undefined) throw new Error("contrato de porta dinâmica sem teto (max)");
  return regra.max;
}

const contratoScript: ContratoPortaDinamica | (typeof PORT_CONTRACTS)["script"] = PORT_CONTRACTS.script;
if (!contratoScript.dynamic) throw new Error("contrato do script deveria ser dinâmico");

/** Teto de portas do bloco Script — do contrato gerado (`MAX_SCRIPT_PORTS`, spec F3 §3.3),
 *  fonte única com `flowgraph.py` (minor 0.2, plano F4a: fecha a cópia local duplicada). */
export const MAX_PORTAS_SCRIPT = tetoDoContrato(contratoScript.rules[0]);

export const ROTULO_BLOCO: Record<TipoBloco, string> = {
  opc_read: "Leitura OPC",
  opc_write: "Escrita OPC",
  script: "Script",
  first_order: "Filtro 1ª ordem",
  kalman: "Filtro Kalman",
  tfs: "TFS",
  mpc: "MPC",
};

/** Defaults dos blocos de filtro (ADR-026), compartilhados por `criarBloco` e `lerNo`: o
 *  bloco recém-arrastado já nasce com uma config que passa no save (`measurement_noise` > 0),
 *  e um `graph_json` com o campo corrompido cai no mesmo valor em vez de virar `NaN`. */
const PADRAO_FIRST_ORDER = { tau: 5 } as const;
const PADRAO_KALMAN = { measurement_noise: 1, process_noise: 0.1 } as const;

export type TipoDadoTag = "float" | "int" | "bool";

/** `tag_id` das tags do projeto ativo, para o espelho de tipagem das portas. */
export type MapaTags = ReadonlyMap<number, TipoDadoTag>;

type DadosBase = { exec_order: number; label: string };

export type DadosTag = DadosBase & { tag_id: number | null };
export type DadosScript = DadosBase & {
  n_inputs: number;
  n_outputs: number;
  code: string;
  output_eu: Record<string, string>;
};

export type ParamsSopdt = { K: number; tau1: number; tau2: number; theta: number };
export type ParamsIopdt = { Ki: number; theta: number };
export type TipoElemento = "sopdt" | "iopdt";

export type ElementoTfs =
  | { enabled: boolean; kind: "sopdt"; params: ParamsSopdt }
  | { enabled: boolean; kind: "iopdt"; params: ParamsIopdt };

/** `matrix[J][K]` é a contribuição de `uK` para `yJ` (spec F3 §3.4); sempre 2x2. */
export type LinhaTfs = [ElementoTfs, ElementoTfs];
export type MatrizTfs = [LinhaTfs, LinhaTfs];

export type DadosTfs = DadosBase & { matrix: MatrizTfs; output_eu: Record<string, string> };

/** `tau` em segundos (RF-532); `0` é passagem direta. */
export type DadosFirstOrder = DadosBase & { tau: number };

/** Os dois campos são **desvio padrão na EU do sinal** (RF-533), nunca variância: o bloco
 *  eleva ao quadrado no runtime. `process_noise` é por varredura, não por segundo. */
export type DadosKalman = DadosBase & { measurement_noise: number; process_noise: number };

export type LimitesMpc = { min: number; max: number };
export type FaixaMpc = { low: number; high: number };
export type ValoresModoPid = { auto: number; target: number };
export type ModoAlvoPid = "rcas" | "cas" | "rout";

/** Tags do PID de uma MV (spec F4 §2.1-3, RF-604); ausente ⇒ MV "direta" (decisão A-8). */
export type PidMv = {
  write_tag_id: number;
  target_mode: ModoAlvoPid;
  mode_cmd_tag_id: number;
  mode_read_tag_id: number | null;
  readback_tag_id: number;
  mode_values: ValoresModoPid;
};

/** `operating_point`/`readback_tag_id` (TD-003): o modelo do MPC é incremental — o builder
 *  alimenta cada par com `coluna - operating_point`, então `operating_point` é o ponto de
 *  linearização. Por isso a porta do bloco fica na coordenada ABSOLUTA da planta (`limits`,
 *  `du_max` e `initial_value` também), sem precisar de um bloco Script somando constantes.
 *  `readback_tag_id` é a posição real da MV DIRETA (sem `pid`, que já tem o seu próprio); em
 *  LOCAL a saída segue essa tag para a transferência bumpless até REMOTO.
 *
 *  `du_min` (TD-007): banda morta do atuador, mesma EU de `du_max` — quem quantiza é o
 *  worker, não o editor; aqui é só o valor de config. `move_weight`: peso multiplicativo do
 *  custo de movimento desta MV no solve. `0`/`1` reproduzem o comportamento anterior a esta
 *  tarefa (config salva antes dela carrega com os mesmos defaults do servidor). */
export type VariavelMv = {
  id: string;
  name: string;
  eu: string;
  limits: LimitesMpc;
  du_max: number;
  du_min: number;
  move_weight: number;
  initial_value: number;
  operating_point: number;
  readback_tag_id: number | null;
  pid: PidMv | null;
};

/** `kind` da linha (CV ou Restrição) define a forma dos `params` do par na matriz `models`
 *  (spec F4 §2.1-2): `selfreg` → SOPDT, `integrating` → IOPDT. */
export type TipoLinhaMpc = "selfreg" | "integrating";

export type VariavelCv = {
  id: string;
  name: string;
  eu: string;
  kind: TipoLinhaMpc;
  tss: number;
  weight: number;
  sp_limits: LimitesMpc;
};

export type VariavelRestricao = {
  id: string;
  name: string;
  eu: string;
  kind: TipoLinhaMpc;
  tss: number;
  range: FaixaMpc;
  priority: number;
};

/** `operating_point` da DV (TD-003): mesmo ponto de linearização das MVs — o builder alimenta
 *  o par com `coluna - operating_point`, então a porta de entrada da DV também fica na
 *  coordenada absoluta da planta, sem bloco Script somando constantes. */
export type VariavelDv = {
  id: string;
  name: string;
  eu: string;
  range: FaixaMpc | null;
  operating_point: number;
};

/** Espelho de `MpcVariables` (spec F4 §2.1): entradas do nó = cvs+constraints+dvs, saída =
 *  mvs, sempre nesta ordem (decisão A-10, `validate.py::_input_handles`/`_output_handles`). */
export type VariaveisMpc = {
  mvs: VariavelMv[];
  cvs: VariavelCv[];
  constraints: VariavelRestricao[];
  dvs: VariavelDv[];
};

/** Par `models[linha][coluna]` (spec F4 §2.1-2); `params` genérico — a forma exata por
 *  `kind` da linha é validação do modal (tarefa 4.2), fora do escopo desta tarefa. */
export type ParModeloMpc = { enabled: boolean; params: Record<string, number> };

/** Espelho de `MpcConfig` (spec F4 §2.1, `mpc_config.py`): `name`/`multiplier` são chaves do
 *  config, distintas de `label` (rótulo genérico de exibição que todo bloco tem). */
export type DadosMpc = DadosBase & {
  name: string;
  multiplier: number;
  variables: VariaveisMpc;
  models: Record<string, Record<string, ParModeloMpc>>;
};

export type DadosBloco =
  | DadosTag
  | DadosScript
  | DadosTfs
  | DadosMpc
  | DadosFirstOrder
  | DadosKalman;

/** `type` é opcional em `Node`; aqui ele é o discriminante e nunca falta. */
type Bloco<D extends Record<string, unknown>, T extends TipoBloco> = Node<D, T> & { type: T };

export type NoLeitura = Bloco<DadosTag, "opc_read">;
export type NoEscrita = Bloco<DadosTag, "opc_write">;
export type NoScript = Bloco<DadosScript, "script">;
export type NoTfs = Bloco<DadosTfs, "tfs">;
export type NoMpc = Bloco<DadosMpc, "mpc">;
export type NoFirstOrder = Bloco<DadosFirstOrder, "first_order">;
export type NoKalman = Bloco<DadosKalman, "kalman">;

export type BlocoNode = NoLeitura | NoEscrita | NoScript | NoTfs | NoMpc | NoFirstOrder | NoKalman;

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

/** Portas fixas do tipo (nome só, na direção pedida) — vem de `PORT_CONTRACTS`
 *  (`contracts.gen.ts`), fonte única com `flowgraph.py` (débito 2+4, plano F4a). Tipo
 *  dinâmico (Script) devolve `[]` aqui: quem resolve é `portasScript`, com a contagem da
 *  config do bloco. */
export function portasFixas(tipo: TipoBloco, direcao: DirecaoPorta): string[] {
  const contrato = PORT_CONTRACTS[tipo];
  if (contrato.dynamic) return [];
  return contrato.ports.filter((porta) => porta.direction === direcao).map((porta) => porta.name);
}

/** Entradas/saídas do MPC são dinâmicas do config, não de `PORT_CONTRACTS` (que só descreve
 *  a *origem* da regra — spec F4 §2.1-5, decisão A-10): entradas = CVs+Restrições+DVs à
 *  esquerda, saída = MVs à direita, na ordem do config; handle = id estável da variável. */
export function handlesEntrada(no: BlocoNode): string[] {
  if (no.type === "script") return portasScript("IN", no.data.n_inputs);
  if (no.type === "mpc") {
    const { cvs, constraints, dvs } = no.data.variables;
    return [...cvs, ...constraints, ...dvs].map((variavel) => variavel.id);
  }
  return portasFixas(no.type, "input");
}

export function handlesSaida(no: BlocoNode): string[] {
  if (no.type === "script") return portasScript("OUT", no.data.n_outputs);
  if (no.type === "mpc") return no.data.variables.mvs.map((mv) => mv.id);
  return portasFixas(no.type, "output");
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
  if (no.type === "mpc") return "num";
  if (no.type === "first_order" || no.type === "kalman") return "num";
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
    case "mpc":
      return { ...no, data: { ...no.data, ...mudanca } };
    case "first_order":
      return { ...no, data: { ...no.data, ...mudanca } };
    case "kalman":
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

/**
 * Descarta as arestas que ficaram penduradas em portas que o bloco não tem mais.
 *
 * Encolher o Script de 3 para 1 entrada apaga `IN2`/`IN3`, e uma aresta apontando para porta
 * inexistente é 422 no save ("'targetHandle' não é uma entrada de..."). Arestas que não
 * tocam o bloco reconfigurado passam intactas.
 */
export function podarArestasDoBloco(edges: readonly BlocoEdge[], no: BlocoNode): BlocoEdge[] {
  const entradas = handlesEntrada(no);
  const saidas = handlesSaida(no);
  return edges.filter((aresta) => {
    if (aresta.source === no.id && !saidas.includes(aresta.sourceHandle)) return false;
    if (aresta.target === no.id && !entradas.includes(aresta.targetHandle)) return false;
    return true;
  });
}

/** Poda as EUs de portas que a nova contagem de saídas do Script não tem mais (spec §4.1-6):
 *  reduzir n_outputs sem descartar a chave sobrando seria 422 no save (`parse.py`
 *  `ScriptConfig._valida_output_eu` rejeita 'output_eu' referenciando porta inexistente). */
export function podarOutputEuScript(
  output_eu: Record<string, string>,
  n_outputs: number,
): Record<string, string> {
  const validas = new Set(portasScript("OUT", n_outputs));
  return Object.fromEntries(Object.entries(output_eu).filter(([porta]) => validas.has(porta)));
}

/**
 * EU herdada por uma porta de ENTRADA (spec §4.1-5): a porta em si não declara EU — segue a
 * aresta que chega em `handle` do nó `no`, acha a porta de SAÍDA de origem, e devolve a EU
 * que essa porta declara em `output_eu_por_no` (mapa nó → `output_eu` do bloco, só populado
 * para Script/TFS). `null` quando não há aresta chegando, ou a origem não declara EU para
 * aquela porta (chave ausente ou `''`, mesmo default de `Tag.eu`).
 *
 * Resolve só UM nível — decisão desta tarefa. Recursar mais um hop (a origem ela mesma
 * herdando de mais um nó atrás) não tem leitura correta aqui: Script não tem mapeamento
 * porta-de-entrada → porta-de-saída (o código é livre, qualquer IN pode alimentar qualquer
 * OUT) e TFS soma até duas entradas por saída (`matrix[j][k]`) — "herdar de qual das duas,
 * com qual EU?" não tem resposta única. Um nível é também a mesma cautela de §4.1-6 (Script
 * não propaga EU da entrada para a própria saída automaticamente): inventar EU atravessando
 * um nó inteiro é pior que deixar a porta sem unidade.
 */
export function euDaPortaDeEntrada(
  edges: readonly BlocoEdge[],
  output_eu_por_no: ReadonlyMap<string, Record<string, string>>,
  no: string,
  handle: string,
): string | null {
  const aresta = edges.find((a) => a.target === no && a.targetHandle === handle);
  if (aresta === undefined) return null;
  const eu = output_eu_por_no.get(aresta.source)?.[aresta.sourceHandle];
  return eu !== undefined && eu !== "" ? eu : null;
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
// Inserção em grade por clique na paleta
// --------------------------------------------------------------------------------------

const COLUNAS_GRADE = 4;
const PASSO_X_GRADE = 250;
const PASSO_Y_GRADE = 170;

function posicaoDoSlot(ancora: XYPosition, indice: number): XYPosition {
  return {
    x: ancora.x + (indice % COLUNAS_GRADE) * PASSO_X_GRADE,
    y: ancora.y + Math.floor(indice / COLUNAS_GRADE) * PASSO_Y_GRADE,
  };
}

/** Posição do próximo nó inserido por clique na paleta: primeiro slot da grade (4 colunas,
 *  passo 250x170) sem nó ocupando a coordenada. Nunca `nodes.length`: um buraco no meio da
 *  grade (nó excluído) faria o próximo nó colidir com o que já ocupa aquele índice, em vez
 *  de tampar o buraco (débito m4-b, plano F4a). */
export function proximaPosicaoNaGrade(
  nodes: readonly BlocoNode[],
  ancora: XYPosition,
): XYPosition {
  const ocupados = new Set(nodes.map((no) => `${String(no.position.x)}:${String(no.position.y)}`));
  let indice = 0;
  for (;;) {
    const posicao = posicaoDoSlot(ancora, indice);
    if (!ocupados.has(`${String(posicao.x)}:${String(posicao.y)}`)) return posicao;
    indice++;
  }
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
        data: { exec_order, label: "", n_inputs: 1, n_outputs: 1, code: "OUT1 = IN1\n", output_eu: {} },
      };
    case "tfs":
      return {
        id,
        type: "tfs",
        position,
        data: { exec_order, label: "", matrix: matrizPadrao(), output_eu: {} },
      };
    case "mpc":
      return {
        id,
        type: "mpc",
        position,
        data: {
          exec_order,
          label: "",
          name: "",
          multiplier: 1,
          variables: { mvs: [], cvs: [], constraints: [], dvs: [] },
          models: {},
        },
      };
    case "first_order":
      return { id, type: "first_order", position, data: { exec_order, label: "", ...PADRAO_FIRST_ORDER } };
    case "kalman":
      return { id, type: "kalman", position, data: { exec_order, label: "", ...PADRAO_KALMAN } };
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

export function objeto(valor: unknown): Record<string, unknown> | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null;
}

export function numero(valor: unknown, padrao: number): number {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : padrao;
}

function inteiro(valor: unknown, padrao: number, minimo: number, maximo: number): number {
  return Math.min(Math.max(Math.trunc(numero(valor, padrao)), minimo), maximo);
}

export function inteiroSimples(valor: unknown, padrao: number): number {
  return Number.isInteger(valor) ? (valor as number) : padrao;
}

export function texto(valor: unknown, padrao: string): string {
  return typeof valor === "string" ? valor : padrao;
}

/** `output_eu` é opcional por porta (spec §4.1-5/6): ausente ou valor não-string vira `{}`,
 *  igual ao servidor (`parse.py::_parse_output_eu`) — compatibilidade retroativa obrigatória. */
function lerOutputEu(bruto: unknown): Record<string, string> {
  const cru = objeto(bruto);
  if (cru === null) return {};
  const saida: Record<string, string> = {};
  for (const [porta, valor] of Object.entries(cru)) {
    if (typeof valor === "string") saida[porta] = valor;
  }
  return saida;
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
          output_eu: lerOutputEu(dados.output_eu),
        },
      };
    case "tfs":
      return {
        id,
        type: tipo,
        position,
        data: { exec_order, label, matrix: lerMatriz(dados.matrix), output_eu: lerOutputEu(dados.output_eu) },
      };
    case "mpc":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          name: texto(dados.name, ""),
          multiplier: inteiro(dados.multiplier, 1, 1, Number.MAX_SAFE_INTEGER),
          variables: lerVariaveisMpc(dados.variables),
          models: lerModelosMpc(dados.models),
        },
      };
    case "first_order":
      return {
        id,
        type: tipo,
        position,
        data: { exec_order, label, tau: numero(dados.tau, PADRAO_FIRST_ORDER.tau) },
      };
    case "kalman":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          measurement_noise: numero(dados.measurement_noise, PADRAO_KALMAN.measurement_noise),
          process_noise: numero(dados.process_noise, PADRAO_KALMAN.process_noise),
        },
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
