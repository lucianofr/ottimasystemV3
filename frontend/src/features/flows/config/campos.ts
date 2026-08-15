import { type ElementoTfs, type LinhaTfs, type MatrizTfs } from "../graph";

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
