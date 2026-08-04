import type { NodeProps, NodeTypes } from "@xyflow/react";

import type { TagOut } from "../../../lib/api";
import { ROTULO_TIPO } from "../../tags/useTags";
import {
  PORTAS_TFS_ENTRADA,
  PORTAS_TFS_SAIDA,
  portasScript,
  type NoEscrita,
  type NoLeitura,
  type NoScript,
  type NoTfs,
} from "../graph";
import { BlocoChapa, LinhaResumo, type Porta } from "./BlocoChapa";
import { useTagsDoEditor } from "./contexto";

/** Portas rotuladas com o próprio nome do handle: é o que o engenheiro vê no 422 do save. */
function portas(ids: readonly string[]): Porta[] {
  return ids.map((id) => ({ id, rotulo: id }));
}

function CorpoTag({ tagId, tag }: { tagId: number | null; tag: TagOut | undefined }) {
  if (tag === undefined) {
    return (
      <p className="text-warn">
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
      saidas={portas(["out"])}
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
      entradas={portas(["in"])}
      saidas={[]}
      blockId={id}
      eu={tag?.eu}
    >
      <CorpoTag tagId={data.tag_id} tag={tag} />
    </BlocoChapa>
  );
}

export function NoScriptPython({ id, data, selected }: NodeProps<NoScript>) {
  const linhas = data.code === "" ? 0 : data.code.split("\n").length;
  return (
    <BlocoChapa
      tipo="script"
      label={data.label}
      execOrder={data.exec_order}
      selecionado={selected}
      entradas={portas(portasScript("IN", data.n_inputs))}
      saidas={portas(portasScript("OUT", data.n_outputs))}
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
      entradas={portas(PORTAS_TFS_ENTRADA)}
      saidas={portas(PORTAS_TFS_SAIDA)}
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
                    : "h-3.5 w-3.5 rounded-[2px] border border-hairline bg-field"
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

/** Referência estável: `nodeTypes` novo a cada render faz o React Flow remontar os nós. */
export const TIPOS_DE_NO: NodeTypes = {
  opc_read: NoLeituraOpc,
  opc_write: NoEscritaOpc,
  script: NoScriptPython,
  tfs: NoTfsMatriz,
};
