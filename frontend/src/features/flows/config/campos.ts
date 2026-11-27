import type { KeyboardEvent } from "react";

import {
  SHED_OPTS,
  type DadosPid,
  type DadosPidLoop,
  type DadosShellMalha,
  type ElementoTfs,
  type LinhaTfs,
  type MatrizTfs,
} from "../graph";

/**
 * Leitura dos campos numéricos do modal.
 *
 * Os campos são `text` com `inputMode="decimal"` em vez de `number`: o engenheiro digita
 * vírgula decimal (pt-BR) e o `input type=number` a descartaria silenciosamente, devolvendo
 * string vazia. Aqui a vírgula é aceita e o valor inválido cai no padrão.
 */
export function numeroDoCampo(bruto: FormDataEntryValue | null, padrao: number): number {
  if (typeof bruto !== "string") return padrao;
  const texto = bruto.trim().replace(",", ".");
  if (texto === "") return padrao;
  const valor = Number(texto);
  return Number.isFinite(valor) ? valor : padrao;
}

/** Tab indenta em vez de sair do campo (spec F3 §6.2: sem editor de código de terceiros). */
export function indentarComTab(evento: KeyboardEvent<HTMLTextAreaElement>): void {
  if (
    evento.key !== "Tab" ||
    evento.shiftKey ||
    evento.ctrlKey ||
    evento.altKey ||
    evento.metaKey
  ) {
    return;
  }
  evento.preventDefault();
  const campo = evento.currentTarget;
  campo.setRangeText("    ", campo.selectionStart, campo.selectionEnd, "end");
}

/** Limite de saída do PID (RF-551, ADR-031): campo em branco vira `null` — sem limite, e o
 *  servidor aceita `null` em `output_min`/`output_max`. Em branco é escolha explícita do
 *  engenheiro; texto ilegível ("8O" em vez de "80") NÃO é, e cai no valor anterior como em
 *  `numeroDoCampo`. Tratar os dois como `null` apagaria em silêncio o teto da MV — que é
 *  também o limite anti-windup da integral — sem erro nenhum na tela. */
export function numeroOuNuloDoCampo(
  bruto: FormDataEntryValue | null,
  padrao: number | null,
): number | null {
  if (typeof bruto !== "string") return padrao;
  const texto = bruto.trim().replace(",", ".");
  if (texto === "") return null;
  const valor = Number(texto);
  return Number.isFinite(valor) ? valor : padrao;
}

export function inteiroDoCampo(
  bruto: FormDataEntryValue | null,
  padrao: number,
  minimo: number,
  maximo: number,
): number {
  return Math.min(Math.max(Math.trunc(numeroDoCampo(bruto, padrao)), minimo), maximo);
}

/** Regra "ausente preserva o valor anterior, vazio vira null, valor converte" (ARCH-20/
 *  TD-024): campo NÃO controlado onde ausência (fora desta submissão, ex.: troca de aba) e
 *  vazio (removido deliberadamente pelo engenheiro) NÃO são a mesma coisa — só o vazio
 *  apaga. `converter` decide se o texto bruto vira um `T` válido ou cai em `null` (ex.:
 *  inteiro positivo, inteiro qualquer, número finito) — cada chamador injeta a validação que
 *  seu campo exige, o combinator só é dono da regra ausente/vazio/valor em si.
 */
export function campoOpcional<T>(
  dados: FormData,
  campo: string,
  atual: T | null,
  converter: (bruto: string) => T | null,
): T | null {
  const bruto = dados.get(campo);
  if (bruto === null) return atual;
  if (typeof bruto !== "string" || bruto === "") return null;
  return converter(bruto);
}

/** Nome do campo de um parâmetro do elemento `yJ/uK`, para casar formulário e matriz. */
export function nomeParam(j: number, k: number, param: string): string {
  return `p${String(j + 1)}${String(k + 1)}_${param}`;
}

/**
 * Reconstrói a matriz a partir do formulário. `enabled`/`kind` vêm do estado do modal — são
 * os controles discretos que decidem quais parâmetros existem — e só os números vêm do DOM.
 * Trocar o `kind` troca o conjunto de params inteiro: params do modelo antigo em `data`
 * seriam chave desconhecida e reprovariam o save com 422.
 */
export function matrizDoFormulario(matriz: MatrizTfs, dados: FormData): MatrizTfs {
  const elemento = (j: number, k: number): ElementoTfs => {
    const atual = matriz[j][k];
    const numero = (param: string, padrao: number): number =>
      numeroDoCampo(dados.get(nomeParam(j, k, param)), padrao);
    if (atual.kind === "iopdt") {
      return {
        enabled: atual.enabled,
        kind: "iopdt",
        params: { Ki: numero("Ki", atual.params.Ki), theta: numero("theta", atual.params.theta) },
      };
    }
    return {
      enabled: atual.enabled,
      kind: "sopdt",
      params: {
        K: numero("K", atual.params.K),
        tau1: numero("tau1", atual.params.tau1),
        tau2: numero("tau2", atual.params.tau2),
        theta: numero("theta", atual.params.theta),
      },
    };
  };
  const linha = (j: number): LinhaTfs => [elemento(j, 0), elemento(j, 1)];
  return [linha(0), linha(1)];
}

/**
 * Reconstrói os campos do PID a partir do formulário (ARCH-19/TD-020). Pura — sem DOM, sem
 * `<dialog>` — para ser testável direto em `pid.check.ts`, no mesmo padrão de
 * `matrizDoFormulario` para o TFS. `label`/`exec_order` são comuns a todo tipo de bloco e
 * ficam por conta de quem chama, como já era no switch original.
 */
export function montarDadosPid(atual: DadosPid, campos: FormData): DadosPid {
  return {
    ...atual,
    kc: numeroDoCampo(campos.get("kc"), atual.kc),
    ti_seconds: numeroDoCampo(campos.get("ti_seconds"), atual.ti_seconds),
    td_seconds: numeroDoCampo(campos.get("td_seconds"), atual.td_seconds),
    setpoint: numeroDoCampo(campos.get("setpoint"), atual.setpoint),
    output_min: numeroOuNuloDoCampo(campos.get("output_min"), atual.output_min),
    output_max: numeroOuNuloDoCampo(campos.get("output_max"), atual.output_max),
    auto_mode: campos.get("auto_mode") === "on",
    proportional_on_measurement: campos.get("proportional_on_measurement") === "on",
    differential_on_measurement: campos.get("differential_on_measurement") === "on",
    starting_output: numeroDoCampo(campos.get("starting_output"), atual.starting_output),
  };
}

/** Modos com caixa de seleção no formulário da casca, na ordem canônica de `permitted`. Modo
 *  fora desta lista (ex.: `iman`) não tem caixa e é preservado de `atual.permitted`. */
export const MODOS_COM_CAIXA = ["oos", "man", "auto", "cas", "rcas", "rout"] as const;

/** Porta de entrada que alimenta cada modo remoto: sem aresta nela o modo não tem de onde ler. */
export const PORTA_DO_MODO_REMOTO: Readonly<Record<string, string>> = {
  cas: "cas_in",
  rcas: "rcas_in",
  rout: "rout_in",
};

/** Caixa de modo remoto sem aresta na porta fica travada — mas NUNCA desmarca sozinha: uma caixa
 *  já marcada continua habilitada, para o engenheiro ver e desfazer a escolha. */
export function caixaDeModoDesabilitada(
  modo: string,
  portasLigadas: ReadonlySet<string>,
  marcado: boolean,
): boolean {
  const porta = PORTA_DO_MODO_REMOTO[modo];
  return porta !== undefined && !portasLigadas.has(porta) && !marcado;
}

/**
 * Reconstrói a casca dos blocos malha (RF-641, RF-642) a partir do formulário. Pura, no padrão de
 * `montarDadosPid`. Contrato do `FormData`: numéricos/nuláveis pelo próprio nome; booleanos por
 * checkbox (marcado = "on", ausente = desmarcado); `direct_acting` por select "true"/"false";
 * `normal`/`shed_opt` por select; `permitted` por uma caixa `permitted_<modo>`.
 * `normal`, `shed_opt` e `direct_acting` ausentes preservam o valor anterior (o select pode não
 * ter sido renderizado). O recorte do fuzzy deixa shed/tracking/feedforward intactos: o
 * `FuzzyLoopConfig` os carrega, mas a tela do fuzzy não os edita.
 */
export function montarDadosShellMalha<T extends DadosShellMalha>(
  atual: T,
  campos: FormData,
  tipo: "pid_loop" | "fuzzy_loop",
): T {
  const numero = (campo: string, padrao: number): number => numeroDoCampo(campos.get(campo), padrao);
  const nulavel = (campo: string, padrao: number | null): number | null =>
    numeroOuNuloDoCampo(campos.get(campo), padrao);
  const marcado = (campo: string): boolean => campos.get(campo) === "on";
  const direta = campos.get("direct_acting");
  const normal = campos.get("normal");
  const shedOpt = campos.get("shed_opt");
  const modosDoFormulario: readonly string[] = MODOS_COM_CAIXA;
  return {
    ...atual,
    direct_acting: direta === null ? atual.direct_acting : direta === "true",
    sp_lo_lim: numero("sp_lo_lim", atual.sp_lo_lim),
    sp_hi_lim: numero("sp_hi_lim", atual.sp_hi_lim),
    sp_rate_up: nulavel("sp_rate_up", atual.sp_rate_up),
    sp_rate_dn: nulavel("sp_rate_dn", atual.sp_rate_dn),
    sp_pv_track_in_man: marcado("sp_pv_track_in_man"),
    out_scale_lo: numero("out_scale_lo", atual.out_scale_lo),
    out_scale_hi: numero("out_scale_hi", atual.out_scale_hi),
    out_lo_lim: numero("out_lo_lim", atual.out_lo_lim),
    out_hi_lim: numero("out_hi_lim", atual.out_hi_lim),
    out_rate_up: nulavel("out_rate_up", atual.out_rate_up),
    out_rate_dn: nulavel("out_rate_dn", atual.out_rate_dn),
    out_startup: numero("out_startup", atual.out_startup),
    pv_ftime: numero("pv_ftime", atual.pv_ftime),
    permitted: [
      ...MODOS_COM_CAIXA.filter((modo) => marcado(`permitted_${modo}`)),
      ...atual.permitted.filter((modo) => !modosDoFormulario.includes(modo)),
    ],
    normal: typeof normal === "string" ? normal : atual.normal,
    ...(tipo === "pid_loop" && {
      shed_opt: SHED_OPTS.find((opcao) => opcao === shedOpt) ?? atual.shed_opt,
      shed_no_return: marcado("shed_no_return"),
      track_enable: marcado("track_enable"),
      track_in_manual: marcado("track_in_manual"),
      trk_val: numero("trk_val", atual.trk_val),
      lo_val: numero("lo_val", atual.lo_val),
      use_pv_for_bkcal: marcado("use_pv_for_bkcal"),
      ff_enable: marcado("ff_enable"),
      ff_gain: numero("ff_gain", atual.ff_gain),
      ff_scale_lo: numero("ff_scale_lo", atual.ff_scale_lo),
      ff_scale_hi: numero("ff_scale_hi", atual.ff_scale_hi),
    }),
  };
}

/** Casca + os 8 campos de sintonia do PID Malha (RF-641). */
export function montarDadosPidLoop(atual: DadosPidLoop, campos: FormData): DadosPidLoop {
  const base = montarDadosShellMalha(atual, campos, "pid_loop");
  const numero = (campo: string, padrao: number): number => numeroDoCampo(campos.get(campo), padrao);
  return {
    ...base,
    kc: numero("kc", base.kc),
    ti_seconds: numero("ti_seconds", base.ti_seconds),
    td_seconds: numero("td_seconds", base.td_seconds),
    n: numero("n", base.n),
    beta: numero("beta", base.beta),
    gamma: numero("gamma", base.gamma),
    gap_band: numero("gap_band", base.gap_band),
    gap_gain: numero("gap_gain", base.gap_gain),
  };
}
