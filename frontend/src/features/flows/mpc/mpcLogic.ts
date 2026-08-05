import type { TagOut } from "../../../lib/api";
import { numeroDoCampo } from "../config/campos";
import type {
  ParModeloMpc,
  TipoLinhaMpc,
  VariaveisMpc,
  VariavelCv,
  VariavelDv,
  VariavelMv,
  VariavelRestricao,
} from "../graph";

/**
 * Lógica pura do modal MPC (tarefa 4.2, spec F4 §2.1): geração de id, derivação de Ts_mpc e
 * reconstrução de variáveis/matriz a partir do `FormData` do formulário — mesmo padrão do
 * TFS (`config/campos.ts`): estrutura (listas, `kind`, presença do `pid`) vive em estado
 * React; valores numéricos/texto são não-controlados e só lidos aqui, no Aplicar.
 */

const PREFIXOS_VARIAVEL = { mv: "mv", cv: "cv", co: "co", dv: "dv" } as const;
export type PrefixoVariavel = keyof typeof PREFIXOS_VARIAVEL;

/** Id estável `<prefixo>_<sufixo>` (spec F4 §2.1-1), gerado na criação, imutável depois.
 *  `aleatorio` é injetável (default `Math.random`) para o teste ser determinístico em vez de
 *  depender de estatística sobre muitas gerações (revisão 4.2 fix 1). */
export function gerarIdVariavel(
  prefixo: PrefixoVariavel,
  aleatorio: () => number = Math.random,
): string {
  const sufixo = aleatorio().toString(36).slice(2, 6);
  return `${PREFIXOS_VARIAVEL[prefixo]}_${sufixo}`;
}

/** `Ts_mpc = multiplier × Ts_flow` (spec F4 §2.2-5, RF-603); exibido read-only na aba Geral. */
export function tsMpcDerivado(multiplier: number, tsFlowSegundos: number): number {
  return multiplier * tsFlowSegundos;
}

/** Nome do campo de um atributo de variável, para casar formulário e id (`var_<id>_<campo>`). */
export function nomeCampoVar(id: string, campo: string): string {
  return `var_${id}_${campo}`;
}

/** Nome do campo de um param da matriz `models`, para casar formulário e par linha/coluna. */
export function nomeCampoModelo(linha: string, coluna: string, param: string): string {
  return `mdl_${linha}_${coluna}_${param}`;
}

function texto(dados: FormData, campo: string, padrao: string): string {
  const bruto = dados.get(campo);
  return typeof bruto === "string" ? bruto.trim() : padrao;
}

export function variavelDvDoFormulario(atual: VariavelDv, dados: FormData): VariavelDv {
  const c = (campo: string): string => nomeCampoVar(atual.id, campo);
  return {
    id: atual.id,
    name: texto(dados, c("name"), atual.name),
    eu: texto(dados, c("eu"), atual.eu),
  };
}

export function variavelMvDoFormulario(
  atual: VariavelMv,
  dados: FormData,
  comPid: boolean,
): VariavelMv {
  const c = (campo: string): string => nomeCampoVar(atual.id, campo);
  const n = (campo: string, padrao: number): number => numeroDoCampo(dados.get(c(campo)), padrao);
  const pidAtual = atual.pid;
  return {
    id: atual.id,
    name: texto(dados, c("name"), atual.name),
    eu: texto(dados, c("eu"), atual.eu),
    limits: { min: n("limits_min", atual.limits.min), max: n("limits_max", atual.limits.max) },
    du_max: n("du_max", atual.du_max),
    initial_value: n("initial_value", atual.initial_value),
    pid: !comPid
      ? null
      : {
          write_tag_id: n("pid_write_tag_id", pidAtual?.write_tag_id ?? 0),
          target_mode:
            (dados.get(c("pid_target_mode")) as "rcas" | "cas" | "rout" | null) ??
            pidAtual?.target_mode ??
            "rcas",
          mode_cmd_tag_id: n("pid_mode_cmd_tag_id", pidAtual?.mode_cmd_tag_id ?? 0),
          mode_read_tag_id: (() => {
            const bruto = dados.get(c("pid_mode_read_tag_id"));
            if (bruto === null || bruto === "") return pidAtual?.mode_read_tag_id ?? null;
            const valor = Number(bruto);
            return Number.isFinite(valor) ? valor : (pidAtual?.mode_read_tag_id ?? null);
          })(),
          readback_tag_id: n("pid_readback_tag_id", pidAtual?.readback_tag_id ?? 0),
          mode_values: {
            auto: n("pid_mode_auto", pidAtual?.mode_values.auto ?? 0),
            target: n("pid_mode_target", pidAtual?.mode_values.target ?? 0),
          },
        },
  };
}

export function variavelCvDoFormulario(atual: VariavelCv, dados: FormData): VariavelCv {
  const c = (campo: string): string => nomeCampoVar(atual.id, campo);
  const n = (campo: string, padrao: number): number => numeroDoCampo(dados.get(c(campo)), padrao);
  return {
    id: atual.id,
    name: texto(dados, c("name"), atual.name),
    eu: texto(dados, c("eu"), atual.eu),
    kind: atual.kind,
    tss: n("tss", atual.tss),
    weight: n("weight", atual.weight),
    sp_limits: {
      min: n("sp_limits_min", atual.sp_limits.min),
      max: n("sp_limits_max", atual.sp_limits.max),
    },
  };
}

export function variavelRestricaoDoFormulario(
  atual: VariavelRestricao,
  dados: FormData,
): VariavelRestricao {
  const c = (campo: string): string => nomeCampoVar(atual.id, campo);
  const n = (campo: string, padrao: number): number => numeroDoCampo(dados.get(c(campo)), padrao);
  return {
    id: atual.id,
    name: texto(dados, c("name"), atual.name),
    eu: texto(dados, c("eu"), atual.eu),
    kind: atual.kind,
    tss: n("tss", atual.tss),
    range: { low: n("range_low", atual.range.low), high: n("range_high", atual.range.high) },
    priority: Math.max(1, Math.trunc(n("priority", atual.priority))),
  };
}

/** Params default por `kind` da linha (spec F4 §2.1-2): SOPDT `{K,tau1,tau2,theta}` /
 *  IOPDT `{Ki,theta}` — trocar o `kind` da linha troca a forma inteira, como no TFS. */
export function paramsPadraoLinha(kind: TipoLinhaMpc): Record<string, number> {
  return kind === "integrating" ? { Ki: 1, theta: 0 } : { K: 1, tau1: 1, tau2: 0, theta: 0 };
}

export function parModeloDoFormulario(
  atual: ParModeloMpc,
  linha: string,
  coluna: string,
  kindLinha: TipoLinhaMpc,
  dados: FormData,
): ParModeloMpc {
  const nomes = kindLinha === "integrating" ? ["Ki", "theta"] : ["K", "tau1", "tau2", "theta"];
  const padrao = paramsPadraoLinha(kindLinha);
  const reconstruido: Record<string, number> = {};
  for (const nome of nomes) {
    reconstruido[nome] = numeroDoCampo(
      dados.get(nomeCampoModelo(linha, coluna, nome)),
      atual.params[nome] ?? padrao[nome] ?? 0,
    );
  }
  return { enabled: atual.enabled, params: reconstruido };
}

/** Tags do projeto filtradas por direção (spec F4 §2.1-3: write/mode_cmd = W, readback/
 *  mode_read = R) para os selects do `pid`. */
export function tagsPorDirecao(tags: readonly TagOut[], direcao: "r" | "w"): readonly TagOut[] {
  return tags.filter((tag) => tag.direction === direcao);
}

// --------------------------------------------------------------------------------------
// Tarefa 4.3 — espelho client-side da validação semântica do MPC (spec F4 §2.2/§7.3-7): as
// mesmas fórmulas e limiares de `ottima_core/flowgraph/mpc_config.py` (`derive_horizons`,
// `mpc_state_dimension`) e `validate.py` (`_check_mpc_caps/_matrix/_numbers/_horizons`),
// reescritos em TS para a aba Resumo bloquear o Aplicar sem round-trip ao servidor. O
// servidor continua a barreira (mesma nota da F3): esta cópia existe só para feedback
// imediato — integridade de tag do `pid` (§2.2-6) fica de fora, pois depende da tabela de
// tags do servidor.
// --------------------------------------------------------------------------------------

// Tetos por categoria de variável (spec §2.2-2, [NOVA]) — mesmos valores de
// `validate.py::_MPC_MV_RANGE/_MPC_CV_RESTRICAO_RANGE/_MPC_DV_RANGE`.
const FAIXA_MV: readonly [number, number] = [1, 4];
const FAIXA_CV_RESTRICAO: readonly [number, number] = [1, 6];
const FAIXA_DV: readonly [number, number] = [0, 4];

export interface Horizontes {
  tsMpc: number;
  np: number;
  nc: number;
}

/** `Ts_mpc = multiplier × Ts_flow`; `Np = ceil(max(TSS)/Ts_mpc)`; `Nc = max(2, ceil(Np/4))`
 *  (spec §2.2-5, RF-603, espelho de `derive_horizons`). `null` quando não há TSS para
 *  derivar (0 CVs+Restrições — já reprovado pelo teto §2.2-2 antes de chegar aqui, mesma
 *  pré-condição documentada em `_check_mpc_horizons`). */
export function derivarHorizontes(
  multiplier: number,
  tsFlowSegundos: number,
  tss: readonly number[],
): Horizontes | null {
  if (tss.length === 0) return null;
  const tsMpc = multiplier * tsFlowSegundos;
  const np = Math.ceil(Math.max(...tss) / tsMpc);
  const nc = Math.max(2, Math.ceil(np / 4));
  return { tsMpc, np, nc };
}

/** Arredondamento banker's (par mais próximo), mesma convenção do `round()` do Python usada
 *  por `mpc_state_dimension` (spec §3.1, nota normativa do débito m2). Só precisa cobrir
 *  `theta/Ts_mpc` ≥ 0 — os dois operandos já são não-negativos por validação (§2.2-4:
 *  `theta ≥ 0`, `Ts_mpc > 0`). */
export function arredondarBankers(valor: number): number {
  const piso = Math.floor(valor);
  const resto = valor - piso;
  if (resto < 0.5) return piso;
  if (resto > 0.5) return piso + 1;
  return piso % 2 === 0 ? piso : piso + 1;
}

/** Dimensão do estado agregado (spec §2.2-7, espelho de `mpc_state_dimension`): 2 estados por
 *  par habilitado SOPDT, 1 por IOPDT, + `round(theta/Ts_mpc)` de atraso por par, + 1 por MV
 *  (estado aumentado `u_prev`, §3.5 — o bias é `_tvp` e não conta). Assume matriz íntegra
 *  (params completos/válidos); o chamador (`validarConfigMpc`) só invoca depois de
 *  confirmar isso, como o servidor faz (`if ts_mpc is not None and matrix_intact`). */
export function dimensaoEstado(
  variaveis: VariaveisMpc,
  modelos: Record<string, Record<string, ParModeloMpc>>,
  tsMpc: number,
): number {
  const kindPorLinha: Record<string, TipoLinhaMpc> = {};
  for (const cv of variaveis.cvs) kindPorLinha[cv.id] = cv.kind;
  for (const co of variaveis.constraints) kindPorLinha[co.id] = co.kind;

  let dimensao = variaveis.mvs.length;
  for (const [linhaId, colunas] of Object.entries(modelos)) {
    const kind = kindPorLinha[linhaId];
    if (kind === undefined) continue; // linha órfã — matriz já podada em `modelosDoFormulario`
    for (const par of Object.values(colunas)) {
      if (!par.enabled) continue;
      dimensao += kind === "selfreg" ? 2 : 1;
      dimensao += arredondarBankers((par.params.theta ?? 0) / tsMpc);
    }
  }
  return dimensao;
}

/** Rótulo legível para mensagens de validação: nome quando preenchido, senão o id estável
 *  (mesmo critério de `rotuloDe`/`avisosInversao` em `graph.ts`). */
export function rotuloVariavel(variavel: { id: string; name: string }): string {
  const nome = variavel.name.trim();
  return nome !== "" ? nome : variavel.id;
}

const PARAMS_SELFREG = ["K", "tau1", "tau2", "theta"] as const;
const PARAMS_INTEGRATING = ["Ki", "theta"] as const;

/** Completude e validade dos `params` de um par por `kind` da linha (spec §2.2-3, espelho de
 *  `_valid_pair_params`): selfreg (SOPDT) exige K≠0, τ1>0, τ2≥0, θ≥0; integrating (IOPDT)
 *  exige Ki≠0, θ≥0 — mesma forma exata, nem mais nem menos chaves. */
function paramsValidosParaKind(kind: TipoLinhaMpc, params: Record<string, number>): boolean {
  const esperados: readonly string[] =
    kind === "integrating" ? PARAMS_INTEGRATING : PARAMS_SELFREG;
  const chaves = Object.keys(params);
  if (chaves.length !== esperados.length || !esperados.every((nome) => nome in params)) {
    return false;
  }
  if (!Object.values(params).every((valor) => Number.isFinite(valor))) return false;
  if (kind === "integrating") return params.Ki !== 0 && params.theta >= 0;
  return params.K !== 0 && params.tau1 > 0 && params.tau2 >= 0 && params.theta >= 0;
}

export interface ResultadoValidacaoMpc {
  erros: string[];
  avisos: string[];
}

/**
 * Espelho client-side de `_check_mpc_caps/_matrix/_numbers/_horizons` + `mpc_state_dimension`
 * (spec §2.2, exceto §2.2-6 integridade de tag do `pid` — fica com o servidor). Usada pela
 * aba Resumo (exibição ao vivo) e pelo `aplicar()` do `MpcModal` (gate do Aplicar: erro
 * bloqueia, aviso não).
 */
export function validarConfigMpc(
  variaveis: VariaveisMpc,
  modelos: Record<string, Record<string, ParModeloMpc>>,
  multiplier: number,
  tsFlowSegundos: number,
): ResultadoValidacaoMpc {
  const erros: string[] = [];
  const avisos: string[] = [];

  const linhas = [...variaveis.cvs, ...variaveis.constraints];
  const colunas = [...variaveis.mvs, ...variaveis.dvs];

  // §2.2-2 — tetos por categoria.
  if (!(FAIXA_MV[0] <= variaveis.mvs.length && variaveis.mvs.length <= FAIXA_MV[1])) {
    erros.push(
      `${String(variaveis.mvs.length)} MV(s) configurada(s); o bloco aceita de ` +
        `${String(FAIXA_MV[0])} a ${String(FAIXA_MV[1])}.`,
    );
  }
  const totalCvRestricao = variaveis.cvs.length + variaveis.constraints.length;
  if (!(FAIXA_CV_RESTRICAO[0] <= totalCvRestricao && totalCvRestricao <= FAIXA_CV_RESTRICAO[1])) {
    erros.push(
      `${String(totalCvRestricao)} CV(s) somadas a Restrições; o bloco aceita de ` +
        `${String(FAIXA_CV_RESTRICAO[0])} a ${String(FAIXA_CV_RESTRICAO[1])}.`,
    );
  }
  if (!(FAIXA_DV[0] <= variaveis.dvs.length && variaveis.dvs.length <= FAIXA_DV[1])) {
    erros.push(
      `${String(variaveis.dvs.length)} DV(s) configurada(s); o bloco aceita de ` +
        `${String(FAIXA_DV[0])} a ${String(FAIXA_DV[1])}.`,
    );
  }

  // §2.2-3 — matriz: cada linha precisa de ≥1 par habilitado cuja coluna é MV; cada MV e cada
  // DV precisam de ≥1 par habilitado; par habilitado exige params completos e válidos.
  const mvComPar: Record<string, boolean> = Object.fromEntries(
    variaveis.mvs.map((mv) => [mv.id, false]),
  );
  const dvComPar: Record<string, boolean> = Object.fromEntries(
    variaveis.dvs.map((dv) => [dv.id, false]),
  );
  let matrizIntegra = true;
  for (const linha of linhas) {
    let linhaComParMv = false;
    for (const coluna of colunas) {
      const par = modelos[linha.id]?.[coluna.id] ?? { enabled: false, params: {} };
      if (!par.enabled) continue;
      if (coluna.id in mvComPar) {
        linhaComParMv = true;
        mvComPar[coluna.id] = true;
      } else {
        dvComPar[coluna.id] = true;
      }
      if (!paramsValidosParaKind(linha.kind, par.params)) {
        matrizIntegra = false;
        erros.push(
          `O par '${rotuloVariavel(linha)}' / '${rotuloVariavel(coluna)}' está habilitado ` +
            `com parâmetros inválidos ou incompletos para o modelo ` +
            `${linha.kind === "integrating" ? "IOPDT" : "SOPDT"}.`,
        );
      }
    }
    if (!linhaComParMv) {
      matrizIntegra = false;
      erros.push(`'${rotuloVariavel(linha)}' não tem nenhum par habilitado cuja coluna é uma MV.`);
    }
  }
  for (const mv of variaveis.mvs) {
    if (mvComPar[mv.id]) continue;
    matrizIntegra = false;
    erros.push(`A MV '${rotuloVariavel(mv)}' não tem nenhum par habilitado na matriz.`);
  }
  for (const dv of variaveis.dvs) {
    if (dvComPar[dv.id]) continue;
    matrizIntegra = false;
    erros.push(`A DV '${rotuloVariavel(dv)}' não tem nenhum par habilitado na matriz.`);
  }

  // §2.2-4 — pisos numéricos (harmoniza a inconsistência apontada na revisão da tarefa 4.2:
  // `priority`/`multiplier` já têm piso de UI — `Math.max(1, Math.trunc(...))` em
  // `variavelRestricaoDoFormulario`/`TabGeneral` —, mas `weight`/`du_max`/`tss` são floats sem
  // nenhum piso de UI; forçar um `Math.max` num float mascararia um erro de digitação em vez
  // de avisar, então o piso deles vive aqui, como erro bloqueante explícito no Resumo).
  for (const mv of variaveis.mvs) {
    if (!(mv.limits.min < mv.limits.max)) {
      erros.push(`A MV '${rotuloVariavel(mv)}' precisa de limite mínimo menor que o máximo.`);
    }
    if (!(mv.du_max > 0)) {
      erros.push(`A MV '${rotuloVariavel(mv)}' precisa de Δu máx. maior que zero.`);
    }
  }
  for (const cv of variaveis.cvs) {
    if (!(cv.tss > 0)) erros.push(`A CV '${rotuloVariavel(cv)}' precisa de TSS maior que zero.`);
    if (!(cv.sp_limits.min < cv.sp_limits.max)) {
      erros.push(`A CV '${rotuloVariavel(cv)}' precisa de SP mínimo menor que o máximo.`);
    }
    if (!(cv.weight > 0)) erros.push(`A CV '${rotuloVariavel(cv)}' precisa de peso maior que zero.`);
  }
  for (const co of variaveis.constraints) {
    if (!(co.tss > 0)) {
      erros.push(`A Restrição '${rotuloVariavel(co)}' precisa de TSS maior que zero.`);
    }
    if (!(co.range.low < co.range.high)) {
      erros.push(`A Restrição '${rotuloVariavel(co)}' precisa de faixa mínima menor que a máxima.`);
    }
  }

  // §2.2-5/7 — horizontes e dimensão de estados (Np<2/Np>120 bloqueiam; Np>60 e dimensão>120
  // são avisos — as duas strings de erro são verbatim ao 422 do servidor, spec §2.2-5).
  const tss = linhas.map((linha) => linha.tss);
  const horizontes = derivarHorizontes(multiplier, tsFlowSegundos, tss);
  if (horizontes !== null) {
    if (horizontes.np < 2) {
      erros.push("multiplicador grande demais para o TSS");
    } else if (horizontes.np > 120) {
      erros.push("aumente o multiplicador ou reduza o TSS");
    } else if (horizontes.np > 60) {
      avisos.push(
        `Np = ${String(horizontes.np)}, acima de 60 — referência de carga do solver (RNF-02).`,
      );
    }
    if (matrizIntegra) {
      const dimensao = dimensaoEstado(variaveis, modelos, horizontes.tsMpc);
      if (dimensao > 120) {
        avisos.push(
          `Dimensão de estados agregada (${String(dimensao)}) acima de 120 — reduza TSS/tempo ` +
            "morto ou o número de pares habilitados (RF-608).",
        );
      }
    }
  }

  return { erros, avisos };
}
