/**
 * Lógica pura do fluxo de import de arquivo de projeto (tarefa 2.4 do plano F6b; spec F6
 * §3.2-5, §6.1-6; F6R-03): partição do `detail` agregado de 422, contagens de
 * conexões/tags/flows e extração dos blocos Script para revisão do admin antes do envio.
 *
 * Sem I/O: `ImportarProjeto.tsx` é quem lê o arquivo (`lerJsonDeArquivo`) e envia
 * (`useImportProject`). O arquivo pode vir de qualquer instalação (ADR-012) e não tem
 * garantia nenhuma de forma até o servidor validar (camadas 1-4, §3.2-4) — todo leitor
 * aqui é tolerante a arquivo malformado e nunca lança; a recusa de verdade é do servidor.
 */

/** `unknown` -> objeto plano, ou `null` se não for (string, número, array, `null`…). Único
 *  ponto de checagem de forma deste módulo. */
export function comoObjeto(valor: unknown): Record<string, unknown> | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Record<string, unknown>)
    : null;
}

function comprimento(valor: unknown): number {
  return Array.isArray(valor) ? valor.length : 0;
}

/** Contagem de conexões/tags/flows do arquivo, para a prévia do passo 2 (spec §6.1-6).
 *  Campo ausente ou de outro tipo conta como 0. */
export interface ContagemBundle {
  connections: number;
  tags: number;
  flows: number;
}

export function contarBundle(bundle: unknown): ContagemBundle {
  const obj = comoObjeto(bundle);
  return {
    connections: comprimento(obj?.connections),
    tags: comprimento(obj?.tags),
    flows: comprimento(obj?.flows),
  };
}

/** Nome inicial do campo editável do passo 2 (decisão A-6): `bundle.project.name`. O que o
 *  admin digitar por cima vai em `name` no corpo do POST e sobrepõe — string vazia aqui só
 *  significa "o campo nasce em branco", nunca um valor a enviar. */
export function nomeInicialDoBundle(bundle: unknown): string {
  const projeto = comoObjeto(comoObjeto(bundle)?.project);
  return typeof projeto?.name === "string" ? projeto.name : "";
}

/** Um bloco Script do arquivo, para a lista com código visível do passo 2 — o ponto de
 *  segurança da tarefa (F6R-03): o `code` executa no `flow-runtime` ao deployar, e o
 *  arquivo pode ter vindo de outra organização (ADR-012), então o admin precisa revisar
 *  antes de importar. */
export interface BlocoScriptImport {
  flow: string;
  label: string;
  code: string;
}

/** Extrai os nós `type === "script"` de `flows[].graph.nodes[]` (forma do arquivo, espelho
 *  de `NoSerializado`/`DadosScript` em `features/flows/graph.ts`). Tolerante a grafo
 *  ausente, `nodes` que não é array, flow ou nó que não é objeto, e nó sem `data` — nunca
 *  lança; a validação de verdade (camada 4, `parse_graph`) é do servidor. Ordem: a do
 *  arquivo, flow a flow, nó a nó. */
export function extrairBlocosScript(bundle: unknown): BlocoScriptImport[] {
  const flows = comoObjeto(bundle)?.flows;
  const blocos: BlocoScriptImport[] = [];
  for (const flowBruto of Array.isArray(flows) ? flows : []) {
    const flow = comoObjeto(flowBruto);
    const nomeFlow = typeof flow?.name === "string" ? flow.name : "";
    const nodes = comoObjeto(flow?.graph)?.nodes;
    for (const noBruto of Array.isArray(nodes) ? nodes : []) {
      const no = comoObjeto(noBruto);
      if (!no || no.type !== "script") continue;
      const data = comoObjeto(no.data);
      const label = typeof data?.label === "string" && data.label.trim() ? data.label : "Script";
      const code = typeof data?.code === "string" ? data.code : "";
      blocos.push({ flow: nomeFlow, label, code });
    }
  }
  return blocos;
}

/** Partição do `detail` agregado de 422 (spec §3.2-5): `"Import recusado (N problemas) |
 *  p1 | p2 | … | e mais N"` vira uma linha por problema, na ordem em que vieram. O
 *  separador é sempre ` | `, nunca `;` — `node_id` de OPC-UA contém `;` legitimamente
 *  (`ns=2;s=TT101`) e quebrar por `;` picotaria um problema em dois (UX-06). `detail` que
 *  não segue esse formato — 409 de nome duplicado, 413 de tamanho, ou o 422 de corpo
 *  não-JSON — não é agregado e volta como item único, o texto inteiro, sem explodir o que
 *  não tem o cabeçalho normativo. */
const CABECALHO_AGREGADO = /^Import recusado \(\d+ problemas\) \| /;

export function particionarDetalhe(detail: string): string[] {
  if (!CABECALHO_AGREGADO.test(detail)) return [detail];
  return detail.replace(CABECALHO_AGREGADO, "").split(" | ");
}
