import { ROTULO_BLOCO, type DadosMpc, type GraphJson, type NoSerializado } from "./graph";

/**
 * Impacto do save num bloco MPC (tarefa 3.3, spec F3): espelho leve do hot-swap do servidor
 * (ADR-024/ADR-011, TD-006) para o diálogo de confirmação do editor. Função pura, sem I/O —
 * o servidor continua sendo a fonte real do que acontece no deploy.
 */
export type ImpactoMpc = {
  blockId: string;
  label: string;
  efeito: "preservado" | "rearme_bumpless" | "reset_local";
};

type NoMpcSerializado = NoSerializado & { readonly data: DadosMpc };

function ehMpc(no: NoSerializado): no is NoMpcSerializado {
  return no.type === "mpc";
}

/**
 * Igualdade estrutural no molde do `==` do Python: objeto compara por chave (ordem
 * irrelevante), lista compara por posição (ordem relevante) — o mesmo contrato que
 * `FlowNode.functional_config()` usa via `dict`/`list` do `model_dump()`.
 */
function igual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((valor, indice) => igual(valor, b[indice]));
  }
  const chavesA = Object.keys(a as Record<string, unknown>);
  const chavesB = Object.keys(b as Record<string, unknown>);
  if (chavesA.length !== chavesB.length) return false;
  const bruto = b as Record<string, unknown>;
  return chavesA.every(
    (chave) =>
      Object.prototype.hasOwnProperty.call(bruto, chave) &&
      igual((a as Record<string, unknown>)[chave], bruto[chave]),
  );
}

/**
 * Espelho de `FlowNode.functional_config()` (`parse.py:148-154`): `type` + `data` SEM
 * `label`/`exec_order` — a posição já fica fora de `data` no editor, então não precisa ser
 * excluída aqui. `data` é tratado como JSON genérico porque `DadosMpc` ganha campos com o
 * tempo (TD-007 `du_min`/`move_weight`) e a comparação deve continuar cobrindo o objeto
 * inteiro sem acompanhar cada campo novo.
 */
function configFuncional(no: NoMpcSerializado): Record<string, unknown> {
  const dados = no.data as unknown as Record<string, unknown>;
  const resto: Record<string, unknown> = { type: no.type };
  for (const chave of Object.keys(dados)) {
    if (chave !== "label" && chave !== "exec_order") resto[chave] = dados[chave];
  }
  return resto;
}

/** Conjunto de ids ordem-insensível (TD-006: reordenar MVs não é "mudar o conjunto"). */
function mesmoConjunto(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const conjuntoA = new Set(a);
  return b.every((id) => conjuntoA.has(id));
}

/**
 * Impacto de um save em cada bloco MPC do grafo ATUAL que já existia no grafo ORIGINAL
 * (bloco novo não tem estado anterior a preservar — fora da lista). Regras (TD-006):
 * - conjunto de ids de MV mudou OU `tsMudou` -> `reset_local` (mesma regra do hot-swap:
 *   Ts muda `reuse={}`, MV muda invalida a instância);
 * - conjunto de MVs igual e `functional_config` mudou -> `rearme_bumpless` (config
 *   resintonizada preserva REMOTO/AUTO com transplante de estado);
 * - `functional_config` igual -> `preservado` (mesma instância, hot-swap nem troca o bloco).
 */
export function impactoDoSave(
  original: GraphJson,
  atual: GraphJson,
  tsMudou: boolean,
): ImpactoMpc[] {
  const originalPorId = new Map(original.nodes.map((no) => [no.id, no]));
  const impactos: ImpactoMpc[] = [];
  for (const no of atual.nodes) {
    if (!ehMpc(no)) continue;
    const anterior = originalPorId.get(no.id);
    if (anterior === undefined || !ehMpc(anterior)) continue;

    const mvsAnterior = anterior.data.variables.mvs.map((mv) => mv.id);
    const mvsAtual = no.data.variables.mvs.map((mv) => mv.id);
    const mvMudou = !mesmoConjunto(mvsAnterior, mvsAtual);
    const efeito: ImpactoMpc["efeito"] =
      mvMudou || tsMudou
        ? "reset_local"
        : igual(configFuncional(anterior), configFuncional(no))
          ? "preservado"
          : "rearme_bumpless";
    const label = no.data.label.trim() || ROTULO_BLOCO.mpc;
    impactos.push({ blockId: no.id, label, efeito });
  }
  return impactos;
}
