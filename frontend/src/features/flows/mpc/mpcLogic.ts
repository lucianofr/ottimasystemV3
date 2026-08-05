import type { TagOut } from "../../../lib/api";
import { numeroDoCampo } from "../config/campos";
import type {
  ParModeloMpc,
  TipoLinhaMpc,
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

/** Id estável `<prefixo>_<sufixo>` (spec F4 §2.1-1), gerado na criação, imutável depois. */
export function gerarIdVariavel(prefixo: PrefixoVariavel): string {
  const sufixo = Math.random().toString(36).slice(2, 6);
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
