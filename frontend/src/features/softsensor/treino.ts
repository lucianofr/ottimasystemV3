/**
 * Lógica pura do treino e dos modelos na página "Coleta e treino" (RF-589, RF-584): sem React,
 * sem rede — testada em `treino.check.ts`. Defaults e limites dos hiperparâmetros saem de
 * `SOFT_SENSOR_HYPERPARAMS` (contrato gerado do Pydantic): a tela nunca digita esses números.
 */

import { SOFT_SENSOR_HYPERPARAMS, type Hiperparametro } from "../../lib/contracts.gen";
import type { DatasetOut, MlJobOut, SoftSensorBlockOut, SoftSensorModelOut } from "./types";

export type MetodoSensor = keyof typeof SOFT_SENSOR_HYPERPARAMS;

export const METODOS: readonly MetodoSensor[] = ["pls", "esn", "lstm"];

/** Decimal com vírgula como o resto da tela; 10 casas para não arredondar um limite como 1e-4. */
const FORMATO_LIMITE = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 10 });
const FORMATO_METRICA = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 });

export function hiperparametrosIniciais(metodo: MetodoSensor): Record<string, number> {
  return Object.fromEntries(
    Object.entries(SOFT_SENSOR_HYPERPARAMS[metodo]).map(([campo, spec]) => [campo, spec.default]),
  );
}

/** `null` = valor aceito. Campo `gt` (`exclusive_min`) recusa o próprio mínimo, mas a mensagem
 *  continua a da faixa. `valor` NaN (campo vazio ou texto) cai na mensagem da faixa. */
export function problemaDoCampo(metodo: MetodoSensor, campo: string, valor: number): string | null {
  const spec = SOFT_SENSOR_HYPERPARAMS[metodo][campo] as Hiperparametro | undefined;
  if (spec === undefined) return "Parâmetro desconhecido";
  if ("choices" in spec) {
    return spec.choices.includes(valor) ? null : `Deve ser um de ${spec.choices.join(", ")}`;
  }
  const acima = spec.exclusive_min === true ? valor > spec.min : valor >= spec.min;
  if (acima && valor <= spec.max) return null;
  return `Deve estar entre ${FORMATO_LIMITE.format(spec.min)} e ${FORMATO_LIMITE.format(spec.max)}`;
}

/** Texto digitado de cada campo -> corpo do POST. Campo com problema fica só em `problemas`. */
export function validarHiperparametros(
  metodo: MetodoSensor,
  textos: Readonly<Record<string, string>>,
): { hiperparametros: Record<string, number>; problemas: Record<string, string> } {
  const hiperparametros: Record<string, number> = {};
  const problemas: Record<string, string> = {};
  for (const campo of Object.keys(SOFT_SENSOR_HYPERPARAMS[metodo])) {
    const texto = (textos[campo] ?? "").trim();
    const valor = texto === "" ? Number.NaN : Number(texto);
    const problema = problemaDoCampo(metodo, campo, valor);
    if (problema === null) hiperparametros[campo] = valor;
    else problemas[campo] = problema;
  }
  return { hiperparametros, problemas };
}

/** Outros conjuntos que o treino aceita juntar a `base` (`load_compatible_datasets`): prontos, com
 *  a mesma variável, as mesmas entradas NA MESMA ORDEM e o mesmo período. O servidor reconfere. */
export function conjuntosCompativeis(
  base: DatasetOut,
  todos: readonly DatasetOut[],
): DatasetOut[] {
  return todos.filter(
    (outro) =>
      outro.id !== base.id &&
      outro.status === "ready" &&
      outro.lab_variable_id === base.lab_variable_id &&
      outro.period_s === base.period_s &&
      outro.input_tag_ids.length === base.input_tag_ids.length &&
      outro.input_tag_ids.every((id, i) => id === base.input_tag_ids[i]),
  );
}

/** Blocos onde o modelo pode ser ativado (o POST confere de novo): mesmo método, mesmo número de
 *  entradas e período inteiro múltiplo do Ts do flow. */
export function blocosCompativeis<
  B extends Pick<SoftSensorBlockOut, "method" | "n_inputs" | "ts_seconds">,
>(
  modelo: Pick<SoftSensorModelOut, "method" | "n_inputs" | "period_s">,
  blocos: readonly B[],
): B[] {
  return blocos.filter((bloco) => {
    const passos = modelo.period_s / bloco.ts_seconds; // Ts 0 vira Infinity
    return (
      bloco.method === modelo.method &&
      bloco.n_inputs === modelo.n_inputs &&
      Number.isFinite(passos) &&
      passos >= 1 &&
      Math.abs(passos - Math.round(passos)) < 1e-9
    );
  });
}

const FRASE_USO = {
  active: "em uso em",
  candidate: "aquecendo em",
  pending: "aguardando o runtime em",
} as const;

export function estadoDoModelo(modelo: Pick<SoftSensorModelOut, "in_use">): string {
  if (modelo.in_use.length === 0) return "—";
  return modelo.in_use
    .map((uso) => `${FRASE_USO[uso.state]} ${uso.flow_name} / ${uso.block_id}`)
    .join("; ");
}

/** `warmup_s` do modelo: `null` quando o meta não traz `warmup_steps`. */
export function formatarAquecimento(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "—";
  const total = Math.round(segundos);
  if (total <= 0) return "nenhum";
  const horas = Math.floor(total / 3600);
  const minutos = Math.floor((total % 3600) / 60);
  const resto = total % 60;
  const partes: string[] = [];
  if (horas > 0) partes.push(`${String(horas)} h`);
  if (minutos > 0) partes.push(`${String(minutos)} min`);
  if (resto > 0 && horas === 0) partes.push(`${String(resto)} s`);
  return partes.join(" ");
}

/** Coluna "Aquecimento" do modelo. Um passo (`warmup_steps = 1`, o PLS) não espera nada além da
 *  primeira amostra, mas a API devolve `warmup_s = 1 x período`: sem esta regra o PLS apareceria
 *  como "1 min", e a spec o mostra como "nenhum" (§8.3). */
export function aquecimentoDoModelo(
  modelo: Pick<SoftSensorModelOut, "warmup_steps" | "warmup_s">,
): string {
  return modelo.warmup_steps === 1 ? "nenhum" : formatarAquecimento(modelo.warmup_s);
}

export function formatarMetrica(valor: number | undefined): string {
  return valor === undefined || !Number.isFinite(valor) ? "—" : FORMATO_METRICA.format(valor);
}

/** Janela de polling rápido depois que ESTE cliente pede uma ativação: o runtime precisa pegar o
 *  `desired` e criar o candidato, e isso só aparece em `/blocks` quando acontece. */
const JANELA_ATIVACAO_MS = 60_000;

/** `ativadoEmMs`: instante (ms) da última ativação bem-sucedida deste cliente, ou `null`. O
 *  relógio entra por parâmetro (`agoraMs`) para a regra ser testada sem esperar. */
export function ativacaoRecente(ativadoEmMs: number | null, agoraMs: number): boolean {
  return ativadoEmMs !== null && agoraMs - ativadoEmMs < JANELA_ATIVACAO_MS;
}

/**
 * Polling rápido (2 s) de `/blocks` só enquanto há candidato aquecendo (`candidate_model_id`) ou
 * dentro da janela da própria ativação (`ativacaoRecente`). Pedido sem candidato (`desired !=
 * active`) NÃO conta: persiste depois de import de projeto, de ativação em flow parado ou de
 * deploy que não carregou o modelo, e `useSoftSensorBlocks` mora no AppShell — contar faria toda
 * página consultar a API a cada 2 s para sempre.
 */
export function precisaAcompanhar(
  blocos: readonly Pick<SoftSensorBlockOut, "candidate_model_id">[] | undefined,
  ativadoEmMs: number | null = null,
  agoraMs: number = Date.now(),
): boolean {
  return (
    ativacaoRecente(ativadoEmMs, agoraMs) ||
    (blocos?.some((bloco) => (bloco.candidate_model_id ?? null) !== null) ?? false)
  );
}

/** Mesma regra vista de `/models`: algum `in_use` aquecendo (`candidate`) ou janela da ativação.
 *  `pending` ("aguardando o runtime") sozinho não mantém o polling. */
export function temTrocaPendente(
  modelos: readonly Pick<SoftSensorModelOut, "in_use">[] | undefined,
  ativadoEmMs: number | null = null,
  agoraMs: number = Date.now(),
): boolean {
  return (
    ativacaoRecente(ativadoEmMs, agoraMs) ||
    (modelos?.some((modelo) => modelo.in_use.some((uso) => uso.state === "candidate")) ?? false)
  );
}

/** `null` sem `epoch`/`epochs` numéricos (PLS e ESN não reportam; a fila e a gravação também
 *  não): a tela desenha o `<progress>` indeterminado. O LSTM conta 1..N no ajuste de 80% e de
 *  novo 1..N no reajuste de 100%, então a época volta para baixo uma vez: cada leitura vale por
 *  si, sem exigir monotonia. */
export function progressoDoTreino(
  progresso: MlJobOut["progress"],
): { feito: number; total: number } | null {
  const { epoch, epochs } = progresso;
  if (typeof epoch !== "number" || typeof epochs !== "number" || !(epochs > 0)) return null;
  return { feito: Math.min(Math.max(epoch, 0), epochs), total: epochs };
}
