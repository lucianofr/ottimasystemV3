import type { NodeProps, NodeTypes } from "@xyflow/react";

import type { TagOut } from "../../../lib/api";
import { ROTULO_TIPO } from "../../tags/useTags";
import {
  portasFixas,
  portasScript,
  type NoEscrita,
  type NoLeitura,
  type NoMpc as NoMpcData,
  type NoScript,
  type NoTfs,
  type VariavelCv,
  type VariavelDv,
  type VariavelMv,
  type VariavelRestricao,
} from "../graph";
import { rotuloVariavel } from "../mpc/mpcLogic";
import { BlocoChapa, LinhaResumo, type Porta } from "./BlocoChapa";
import { useTagsDoEditor } from "./contexto";

/** Portas rotuladas com o próprio nome do handle: é o que o engenheiro vê no 422 do save. */
function portas(ids: readonly string[]): Porta[] {
  return ids.map((id) => ({ id, rotulo: id }));
}

/** Portas de SAÍDA do Script/TFS com a EU declarada por porta (spec §4.1, §6.4): mesmo
 *  tratamento tipográfico que `ValorPorta` já dá à EU de OPC-Read/Write, só que por handle
 *  em vez de por bloco inteiro — cada porta de saída pode ter a sua. Chave ausente ou `''`
 *  em `output_eu` cai em `undefined` (sem unidade), igual ao default de `Tag.eu`. */
function portasComEu(ids: readonly string[], output_eu: Record<string, string>): Porta[] {
  return ids.map((id) => ({ id, rotulo: id, eu: output_eu[id] }));
}

/** Portas do MPC rotulam `nome (EU)` — ao contrário do resto do canvas, que rotula pelo
 *  handle id (decisão A-10, spec F4 §7.2). Nome vazio cai no id (variável ainda sem nome). */
function portasMpc(
  variaveis: readonly (VariavelMv | VariavelCv | VariavelRestricao | VariavelDv)[],
): Porta[] {
  return variaveis.map((variavel) => {
    const nome = rotuloVariavel(variavel);
    return { id: variavel.id, rotulo: variavel.eu ? `${nome} (${variavel.eu})` : nome };
  });
}

function CorpoTag({ tagId, tag }: { tagId: number | null; tag: TagOut | undefined }) {
  if (tag === undefined) {
    return (
      <p className="text-warn-fg">
        {tagId === null ? "Tag não configurada" : "Tag fora do projeto ativo"}
      </p>
    );
  }
  return (
    <div className="space-y-0.5">
      <LinhaResumo rotulo="Tag" valor={tag.name} />
      <LinhaResumo
        rotulo="Tipo"
        valor={`${ROTULO_TIPO[tag.data_type]}${tag.eu ? ` · ${tag.eu}` : ""}`}
      />
    </div>
  );
}

export function NoLeituraOpc({ id, data, selected }: NodeProps<NoLeitura>) {
  const tags = useTagsDoEditor();
  const tag = data.tag_id === null ? undefined : tags.get(data.tag_id);
  return (
    <BlocoChapa
      tipo="opc_read"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={[]}
      saidas={portas(portasFixas("opc_read", "output"))}
      blockId={id}
      eu={tag?.eu}
    >
      <CorpoTag tagId={data.tag_id} tag={tag} />
    </BlocoChapa>
  );
}

export function NoEscritaOpc({ id, data, selected }: NodeProps<NoEscrita>) {
  const tags = useTagsDoEditor();
  const tag = data.tag_id === null ? undefined : tags.get(data.tag_id);
  return (
    <BlocoChapa
      tipo="opc_write"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasFixas("opc_write", "input"))}
      saidas={[]}
      blockId={id}
      eu={tag?.eu}
    >
      <CorpoTag tagId={data.tag_id} tag={tag} />
    </BlocoChapa>
  );
}

/** EU por porta de saída (spec §4.1, tarefa 5.2): cada `OUT<n>`/`y1`/`y2` mostra a unidade
 *  que `output_eu` declarar para aquela porta específica, mesmo tratamento tipográfico das
 *  portas de OPC-Read/Write (`ValorPorta`, mono tabular + EU em Texto Secundário menor).
 *  Porta sem EU declarada mostra só o valor — EU é opcional (§4.1-5). Entradas não mostram
 *  EU herdada aqui: `euDaPortaDeEntrada` (`graph.ts`) resolve a herança e é testada em
 *  isolado (`graph.check.ts`); nada no canvas ainda a consome (fora do escopo desta tarefa,
 *  que cobre só a declaração na porta de saída, §6.4). */
export function NoScriptPython({ id, data, selected }: NodeProps<NoScript>) {
  const linhas = data.code === "" ? 0 : data.code.split("\n").length;
  return (
    <BlocoChapa
      tipo="script"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasScript("IN", data.n_inputs))}
      saidas={portasComEu(portasScript("OUT", data.n_outputs), data.output_eu)}
      blockId={id}
    >
      <div className="space-y-0.5">
        <LinhaResumo
          rotulo="Portas"
          valor={`${String(data.n_inputs)} entrada(s) · ${String(data.n_outputs)} saída(s)`}
        />
        <LinhaResumo rotulo="Código" valor={`${String(linhas)} linha(s)`} />
      </div>
    </BlocoChapa>
  );
}

/** Mini matriz 2x2: quadradinho aceso = elemento habilitado (linha yJ, coluna uK). */
export function NoTfsMatriz({ id, data, selected }: NodeProps<NoTfs>) {
  const habilitados = data.matrix.flat().filter((elemento) => elemento.enabled).length;
  return (
    <BlocoChapa
      tipo="tfs"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasFixas("tfs", "input"))}
      saidas={portasComEu(portasFixas("tfs", "output"), data.output_eu)}
      blockId={id}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="grid grid-cols-2 gap-0.5">
          {data.matrix.map((linha, j) =>
            linha.map((elemento, k) => (
              <span
                key={`y${String(j + 1)}u${String(k + 1)}`}
                title={`y${String(j + 1)} / u${String(k + 1)}: ${
                  elemento.enabled ? elemento.kind.toUpperCase() : "desabilitado"
                }`}
                className={
                  elemento.enabled
                    ? "h-3.5 w-3.5 rounded-[2px] border border-accent bg-accent"
                    : "h-3.5 w-3.5 rounded-[2px] border border-border bg-bg"
                }
              />
            )),
          )}
        </div>
        <LinhaResumo rotulo="Habilitados" valor={`${String(habilitados)} de 4`} />
      </div>
    </BlocoChapa>
  );
}

/** Portas dinâmicas do config (spec F4 §7.2, decisão A-10): entradas = CVs+Restrições+DVs à
 *  esquerda, saída = MVs à direita, na ordem do config; sem variáveis ⇒ sem portas
 *  (B-F4-01 passo 5). */
export function NoMpc({ id, data, selected }: NodeProps<NoMpcData>) {
  const { mvs, cvs, constraints, dvs } = data.variables;
  const entradas = portasMpc([...cvs, ...constraints, ...dvs]);
  const saidas = portasMpc(mvs);
  return (
    <BlocoChapa
      tipo="mpc"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={entradas}
      saidas={saidas}
      blockId={id}
    >
      <div className="space-y-0.5">
        <LinhaResumo rotulo="Nome" valor={data.name.trim() || "—"} />
        <LinhaResumo
          rotulo="Variáveis"
          valor={`${String(mvs.length)} MV · ${String(cvs.length)} CV · ${String(constraints.length)} restrição(ões) · ${String(dvs.length)} DV`}
        />
      </div>
    </BlocoChapa>
  );
}

/** Referência estável: `nodeTypes` novo a cada render faz o React Flow remontar os nós. */
export const TIPOS_DE_NO: NodeTypes = {
  opc_read: NoLeituraOpc,
  opc_write: NoEscritaOpc,
  script: NoScriptPython,
  tfs: NoTfsMatriz,
  mpc: NoMpc,
};
