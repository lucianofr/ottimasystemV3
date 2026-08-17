import type { Edge, Node, XYPosition } from "@xyflow/react";
import {
  PORT_CONTRACTS,
  type ConstraintVar,
  type ContratoPortaDinamica,
  type CvVar,
  type DirecaoPorta,
  type DvVar,
  type FuzzyConfig,
  type IopdtParams,
  type Limits,
  type ModeValues,
  type MpcConfig,
  type MpcVariables,
  type MvVar,
  type PairModel,
  type PidBinding,
  type PidConfig,
  type Range,
  type RegraPortaDinamica,
  type ScriptConfig,
  type SopdtParams,
} from "../../lib/contracts.gen";
import { lerModelosMpc, lerVariaveisMpc } from "./mpc/graphMpc";
import { PADRAO_FIRST_ORDER, PADRAO_KALMAN, PADRAO_PID, REGISTRO_BLOCO, ROTULO_BLOCO } from "./registro";

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
  "fuzzy",
  "pid",
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

/** Forma do contrato do bloco Fuzzy após a regeneração (`contracts_export.py::PORT_CONTRACTS`,
 *  ADR-029): estende o contrato dinâmico padrão com o FLL e as contagens padrão que o
 *  servidor define, para `criarBloco`/`lerNo` nunca duplicarem esse literal aqui. */
type ContratoFuzzy = ContratoPortaDinamica & {
  default_fll: string;
  default_counts: { n_inputs: number; n_outputs: number };
  max_fll_length: number;
};

export const contratoFuzzy = PORT_CONTRACTS.fuzzy as ContratoFuzzy;
if (!contratoFuzzy.dynamic) throw new Error("contrato do fuzzy deveria ser dinâmico");

/** Teto de portas do bloco Fuzzy — do contrato gerado (RF-541), mesma fonte única que
 *  `MAX_PORTAS_SCRIPT`. */
export const MAX_PORTAS_FUZZY = tetoDoContrato(contratoFuzzy.rules[0]);

/** Teto do texto FLL colado (FUZZY-SEC-02) — espelho de `MAX_FUZZY_FLL_LENGTH` no
 *  contrato, mesma fonte única: o backend reprova acima deste tamanho. */
export const MAX_FLL_LENGTH = contratoFuzzy.max_fll_length;

/** Rótulo por tipo (ARCH-18/TD-021): concentrado em `registro.ts` junto com
 *  descrição/defaults/componente — reexportado aqui porque a maioria dos consumidores já
 *  importa de `graph.ts`, e trocar 6 arquivos de import só para mover o dono não paga o
 *  frete. `PADRAO_FIRST_ORDER`/`PADRAO_KALMAN`/`PADRAO_PID` (usados abaixo, em `lerNo`)
 *  moraram aqui antes; também concentrados em `registro.ts` (Locality: dados do tipo
 *  ficam juntos). */
export { ROTULO_BLOCO };

export type TipoDadoTag = "float" | "int" | "bool";

/** `tag_id` das tags do projeto ativo, para o espelho de tipagem das portas. */
export type MapaTags = ReadonlyMap<number, TipoDadoTag>;

export type DadosBase = { exec_order: number; label: string };

export type DadosTag = DadosBase & { tag_id: number | null };
/** `Pick<T, keyof T>`, não `DadosBase & ScriptConfig` puro: `ScriptConfig` é uma
 *  `interface` gerada, e o TS não aceita `interface` referenciada direto onde o genérico de
 *  `Node<D, T>` (`@xyflow/react`) exige `D extends Record<string, unknown>` — falta o índice
 *  implícito que um alias de objeto tem. `Pick` materializa um tipo mapeado (mesma forma,
 *  sem esse problema); mesmo ajuste em `DadosFuzzy`/`DadosPid` abaixo. */
export type DadosScript = DadosBase & Pick<ScriptConfig, keyof ScriptConfig>;

/** `n_inputs`/`n_outputs` mapeiam posicionalmente às `InputVariable`/`OutputVariable`
 *  declaradas no `fll`, na ordem de declaração (RF-541, ADR-029). */
export type DadosFuzzy = DadosBase & Pick<FuzzyConfig, keyof FuzzyConfig>;

/** `SopdtParams`/`IopdtParams` (`parse.py::TfsElement`) são planas — sobrevivem à geração
 *  (ARCH-06/TD-018) sem ressalva. `ElementoTfs`/`DadosTfs` continuam manuais: no Pydantic,
 *  `TfsElement.params: SopdtParams | IopdtParams` é uma união NÃO discriminada (sem
 *  `Field(discriminator=...)`), então `model_json_schema()` emite só um `anyOf` solto, sem
 *  vínculo com o campo irmão `kind` — o TS gerado não conseguiria estreitar `params` a partir
 *  de `kind` (é exatamente o que `valorParam`/`trocarElemento`, em `CamposTfs.tsx`, fazem
 *  hoje). Ligar as duas coisas exigiria reescrever `TfsElement` como union tagged no Pydantic
 *  — fora do escopo cirúrgico deste item (`mpc_config.py`/`parse.py` não estão no Target). */
export type ParamsSopdt = SopdtParams;
export type ParamsIopdt = IopdtParams;
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

/** `tau < Ts/DIRECT_PASS_RATIO` degrada o estágio para passagem direta — mesmo limiar do
 *  runtime (`services/flow-runtime/.../blocks/lag.py::DIRECT_PASS_RATIO`), espelhado aqui só
 *  para o rótulo do nó (TD-011): o engenheiro não deveria precisar dividir o Ts de cabeça
 *  para descobrir que o filtro está desligado. Igualdade exata no limiar continua dinâmica
 *  (`tau >= Ts/10`), mesmo teste de fronteira do runtime. */
export const DIRECT_PASS_RATIO = 10;

export function passagemDireta(tau: number, tsFlowSegundos: number): boolean {
  return tau === 0 || tau < tsFlowSegundos / DIRECT_PASS_RATIO;
}

/** Os dois campos são **desvio padrão na EU do sinal** (RF-533), nunca variância: o bloco
 *  eleva ao quadrado no runtime. `process_noise` é por varredura, não por segundo. */
export type DadosKalman = DadosBase & { measurement_noise: number; process_noise: number };

/** ISA (Kc/Ti/Td), não paralelo (Kp/Ki/Kd) — `criarBloco`/runtime convertem uma vez na
 *  construção (ADR-031, RF-551..554). `ti_seconds === 0` desliga a ação integral (evita
 *  divisão por zero, permite controle P/PD); `td_seconds === 0` desliga a derivativa.
 *  `output_min`/`output_max` nulos = sem limite; quando os dois existem, `output_min` deve
 *  ser estritamente menor que `output_max` (limites iguais travam a saída, erro de config).
 *  `sample_time`/`error_map`/`time_fn` do `simple-pid` ficam de fora por decisão do gate: o
 *  laço de varredura é a única autoridade de tempo, e os outros dois são callables Python,
 *  não serializáveis em JSON. */
export type DadosPid = DadosBase & Pick<PidConfig, keyof PidConfig>;

/** `LimitesMpc`/`FaixaMpc`/`ValoresModoPid`/`PidMv` abaixo viram alias do tipo gerado
 *  (ARCH-06/TD-018): `Limits`/`Range`/`ModeValues`/`PidBinding` de `mpc_config.py`, mesmo
 *  mecanismo de `contracts_export.py::build_contracts()["node_configs"]`.
 *
 *  `ModoAlvoPid`/`TipoLinhaMpc`/`ObjetivoMv`/`ObjetivoCv`/`ObjetivoRestricao`/`AcaoFalhaMv`/
 *  `AcaoFalhaLinha` continuam declarados à mão: no Pydantic eles nascem de `Literal[...]`
 *  atribuído a uma variável comum (`RowKind = Literal["selfreg", "integrating"]` etc.), e
 *  `model_json_schema()` só nomeia um `$defs` para esse padrão quando a declaração usa a
 *  sintaxe de alias do PEP 695 (`type RowKind = Literal[...]`, testado à mão neste item) —
 *  `mpc_config.py` usa a forma antiga, então cada `Literal` aparece só inline, sem nome, no
 *  campo que o usa (ex.: `MvVar.objective` em `contracts.gen.ts` carrega a união solta, sem
 *  um `ObjetivoMv` para importar). Migrar `mpc_config.py` para PEP 695 resolveria, mas esse
 *  arquivo não está no Target deste item. */
export type LimitesMpc = Limits;
export type FaixaMpc = Range;
export type ValoresModoPid = ModeValues;
export type ModoAlvoPid = "rcas" | "cas" | "rout";

/** Tags do PID de uma MV (spec F4 §2.1-3, RF-604); ausente ⇒ MV "direta" (decisão A-8). */
export type PidMv = PidBinding;

/** `kind` da linha (CV ou Restrição) define a forma dos `params` do par na matriz `models`
 *  (spec F4 §2.1-2): `selfreg` → SOPDT, `integrating` → IOPDT. */
export type TipoLinhaMpc = "selfreg" | "integrating";

/** Função objetivo da variável no SSTO (ADR-027 §9 estendido) — espelho de
 *  `MvObjective`/`CvObjective`/`ConstraintObjective` do `mpc_config.py`. `none` (default)
 *  = comportamento anterior; config salvo antes da feature carrega com ele. */
export type ObjetivoMv = "none" | "maximize" | "minimize" | "psv" | "equalize";
export type ObjetivoCv = "none" | "maximize" | "minimize" | "observe_limit" | "target" | "psv";
export type ObjetivoRestricao = "none" | "maximize" | "minimize";

/** Ação de falha por variável (RF-613) — espelho de `MvFailAction`/`RowFailAction`:
 *  avaliada só em REMOTO, debounce de 2 execuções; `simulate_*` (só linhas) segura o valor
 *  previsto por até `fail_timeout_s` antes da ação final. */
export type AcaoFalhaMv = "no_action" | "shed_local" | "manual";
export type AcaoFalhaLinha =
  | "no_action"
  | "shed_local"
  | "manual"
  | "simulate_manual"
  | "simulate_shed_local";

/** Espelho de `MvVar` (`mpc_config.py`), gerado via `contracts.gen.ts` (ARCH-06/TD-018).
 *  `operating_point`/`readback_tag_id` (TD-003): o modelo do MPC é incremental — o builder
 *  alimenta cada par com `coluna - operating_point`, então `operating_point` é o ponto de
 *  linearização. Por isso a porta do bloco fica na coordenada ABSOLUTA da planta (`limits`,
 *  `max_rate` e `initial_value` também), sem precisar de um bloco Script somando constantes.
 *  `readback_tag_id` é a posição real da MV DIRETA (sem `pid`, que já tem o seu próprio); em
 *  LOCAL a saída segue essa tag para a transferência bumpless até REMOTO.
 *
 *  `zero`/`span` (RF-609): faixa de instrumento `[zero, zero+span]` — os ganhos da matriz
 *  são declarados %/% e o motor converte a EU por `span_linha/span_coluna`; o faceplate usa
 *  a faixa como escala. `max_rate` (RF-604 revisado): taxa máxima em EU/s (era `du_max` em
 *  EU/ciclo — o Δu do solve é `max_rate × Ts_mpc`).
 *
 *  `du_min` (TD-007): banda morta do atuador, na EU da MV — quem quantiza é o worker, não o
 *  editor; aqui é só o valor de config. `move_weight`: peso multiplicativo do custo de
 *  movimento desta MV no solve. `0`/`1` reproduzem o comportamento anterior a esta tarefa
 *  (config salvo antes dela carrega com os mesmos defaults do servidor).
 *
 *  `fail_action` (RF-613): ação quando a MV fica indisponível em REMOTO. `local_shed_mode`:
 *  valor escrito no `mode_cmd` em qualquer devolução ao local; `null` = `mode_values.auto`
 *  (só com PID — o servidor valida). */
export type VariavelMv = MvVar;

export type VariavelCv = CvVar;

export type VariavelRestricao = ConstraintVar;

/** `operating_point` da DV (TD-003): mesmo ponto de linearização das MVs — o builder alimenta
 *  o par com `coluna - operating_point`, então a porta de entrada da DV também fica na
 *  coordenada absoluta da planta, sem bloco Script somando constantes. `zero`/`span`
 *  (RF-609): faixa de instrumento — entra na conversão %/%→EU dos ganhos da DV. */
export type VariavelDv = DvVar;

/** Espelho de `MpcVariables` (spec F4 §2.1): entradas do nó = cvs+constraints+dvs, saída =
 *  mvs, sempre nesta ordem (decisão A-10, `validate.py::_input_handles`/`_output_handles`). */
export type VariaveisMpc = MpcVariables;

/** Par `models[linha][coluna]` (spec F4 §2.1-2); `params` genérico — a forma exata por
 *  `kind` da linha é validação do modal (tarefa 4.2), fora do escopo desta tarefa. */
export type ParModeloMpc = PairModel;

/** Espelho de `MpcConfig` (spec F4 §2.1, `mpc_config.py`): `name`/`multiplier` são chaves do
 *  config, distintas de `label` (rótulo genérico de exibição que todo bloco tem). `economics`
 *  fica de fora por enquanto: `lerNo`/`criarBloco` (case "mpc") nunca leram nem escreveram
 *  esse campo — o editor não tem UI para o SSTO ainda; estendê-lo é fora do escopo do
 *  ARCH-06/TD-018 (gerar a forma existente, não abrir superfície nova do editor). */
export type DadosMpc = DadosBase & Pick<MpcConfig, "name" | "multiplier" | "variables" | "models">;

export type DadosBloco =
  | DadosTag
  | DadosScript
  | DadosTfs
  | DadosMpc
  | DadosFirstOrder
  | DadosKalman
  | DadosFuzzy
  | DadosPid;

/** `type` é opcional em `Node`; aqui ele é o discriminante e nunca falta. */
type Bloco<D extends Record<string, unknown>, T extends TipoBloco> = Node<D, T> & { type: T };

export type NoLeitura = Bloco<DadosTag, "opc_read">;
export type NoEscrita = Bloco<DadosTag, "opc_write">;
export type NoScript = Bloco<DadosScript, "script">;
export type NoTfs = Bloco<DadosTfs, "tfs">;
export type NoMpc = Bloco<DadosMpc, "mpc">;
export type NoFirstOrder = Bloco<DadosFirstOrder, "first_order">;
export type NoKalman = Bloco<DadosKalman, "kalman">;
export type NoFuzzy = Bloco<DadosFuzzy, "fuzzy">;
export type NoPid = Bloco<DadosPid, "pid">;

export type BlocoNode =
  | NoLeitura
  | NoEscrita
  | NoScript
  | NoTfs
  | NoMpc
  | NoFirstOrder
  | NoKalman
  | NoFuzzy
  | NoPid;

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
  if (no.type === "fuzzy") return portasScript("IN", no.data.n_inputs);
  if (no.type === "mpc") {
    const { cvs, constraints, dvs } = no.data.variables;
    return [...cvs, ...constraints, ...dvs].map((variavel) => variavel.id);
  }
  return portasFixas(no.type, "input");
}

/** Portas fixas de saída do MPC (decisão A-10 REVISTA 2026-08-17, spec F4 §2.1-5): eixos
 *  de modo do próprio bloco (RF-621), não uma variável do usuário — ao contrário das
 *  demais portas do MPC (uma por variável), estas 2 SEMPRE existem, mesmo no nó recém-
 *  criado sem nenhuma MV/CV. `PORTA_MPC_LOCAL`: 1 em LOCAL, 0 em REMOTO. `PORTA_MPC_AUTO`:
 *  1 em AUTO (dentro de REMOTO), 0 em MAN. Único ponto de definição da string no frontend —
 *  `NoMpc` (nodes/index.tsx) importa daqui. Espelha `MPC_PORT_LOCAL`/`MPC_PORT_AUTO`
 *  (`ottima_core.flowgraph.mpc_config`), hand-mirrado (mesmo padrão de `DIRECT_PASS_RATIO`
 *  acima): sem geração cruzada de linguagem para 2 literais. */
export const PORTA_MPC_LOCAL = "local";
export const PORTA_MPC_AUTO = "auto";

export function handlesSaida(no: BlocoNode): string[] {
  if (no.type === "script") return portasScript("OUT", no.data.n_outputs);
  if (no.type === "fuzzy") return portasScript("OUT", no.data.n_outputs);
  if (no.type === "mpc") {
    return [...no.data.variables.mvs.map((mv) => mv.id), PORTA_MPC_LOCAL, PORTA_MPC_AUTO];
  }
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
  if (no.type === "fuzzy") return "num";
  if (no.type === "pid") return "num";
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

/** Atualiza campos comuns de `data`; id, posição e config seguem intactos (ADR-024).
 *  Sem switch (ARCH-18/TD-021): nenhum `case` fazia trabalho por tipo — todo braço era
 *  `{...no.data, ...mudanca}` idêntico; o switch existia só porque o TS não estreita
 *  `no.data` por `no.type` sem narrowing explícito. O cast documenta essa lacuna do
 *  compilador, não uma lacuna de tipo real. */
export function comDados(no: BlocoNode, mudanca: Partial<DadosBase>): BlocoNode {
  return { ...no, data: { ...no.data, ...mudanca } } as BlocoNode;
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

/** Poda as EUs de portas que a nova contagem de saídas não tem mais (spec §4.1-6, RF-541):
 *  reduzir a contagem sem descartar a chave sobrando seria 422 no save (`parse.py`
 *  `_valida_output_eu` rejeita 'output_eu' referenciando porta inexistente). Paramétrico em
 *  prefixo+contagem: Script e Fuzzy compartilham a mesma regra de poda em vez de duas
 *  funções quase idênticas. */
export function podarOutputEu(
  prefixo: "IN" | "OUT",
  output_eu: Record<string, string>,
  quantidade: number,
): Record<string, string> {
  const validas = new Set(portasScript(prefixo, quantidade));
  return Object.fromEntries(Object.entries(output_eu).filter(([porta]) => validas.has(porta)));
}

/**
 * EU herdada por uma porta de ENTRADA (spec §4.1-5): a porta em si não declara EU — segue a
 * aresta que chega em `handle` do nó `no`, acha a porta de SAÍDA de origem, e devolve a EU
 * que essa porta declara em `output_eu_por_no` (mapa nó → `output_eu` do bloco, só populado
 * para Script/TFS/Fuzzy). `null` quando não há aresta chegando, ou a origem não declara EU
 * para aquela porta (chave ausente ou `''`, mesmo default de `Tag.eu`).
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

/** ARCH-18/TD-021: `REGISTRO_BLOCO[tipo].defaults()` sempre bate com o shape de
 *  `Dados<Tipo>` — a completude vem de `Record<TipoBloco, DefinicaoBloco>` (erro de build
 *  se um tipo faltar no registro), não de union discriminada; o TS não prova essa
 *  correlação tipo-a-tipo sem voltar a um switch, então o cast é a única fronteira não
 *  verificada, documentada aqui. */
export function criarBloco(
  tipo: TipoBloco,
  id: string,
  position: XYPosition,
  exec_order: number,
): BlocoNode {
  return {
    id,
    type: tipo,
    position,
    data: { exec_order, label: "", ...REGISTRO_BLOCO[tipo].defaults() },
  } as BlocoNode;
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
    case "fuzzy":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          n_inputs: inteiro(dados.n_inputs, 0, 0, MAX_PORTAS_FUZZY),
          n_outputs: inteiro(dados.n_outputs, 0, 0, MAX_PORTAS_FUZZY),
          fll: texto(dados.fll, contratoFuzzy.default_fll),
          output_eu: lerOutputEu(dados.output_eu),
        },
      };
    case "pid":
      return {
        id,
        type: tipo,
        position,
        data: {
          exec_order,
          label,
          kc: numero(dados.kc, PADRAO_PID.kc),
          ti_seconds: numero(dados.ti_seconds, PADRAO_PID.ti_seconds),
          td_seconds: numero(dados.td_seconds, PADRAO_PID.td_seconds),
          setpoint: numero(dados.setpoint, PADRAO_PID.setpoint),
          output_min: dados.output_min === null ? null : numero(dados.output_min, PADRAO_PID.output_min),
          output_max: dados.output_max === null ? null : numero(dados.output_max, PADRAO_PID.output_max),
          auto_mode: typeof dados.auto_mode === "boolean" ? dados.auto_mode : PADRAO_PID.auto_mode,
          proportional_on_measurement:
            typeof dados.proportional_on_measurement === "boolean"
              ? dados.proportional_on_measurement
              : PADRAO_PID.proportional_on_measurement,
          differential_on_measurement:
            typeof dados.differential_on_measurement === "boolean"
              ? dados.differential_on_measurement
              : PADRAO_PID.differential_on_measurement,
          starting_output: numero(dados.starting_output, PADRAO_PID.starting_output),
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
