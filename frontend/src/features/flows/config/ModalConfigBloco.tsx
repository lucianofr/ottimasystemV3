import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { TagOut } from "../../../lib/api";
import { ROTULO_TIPO } from "../../tags/useTags";
import {
  MAX_PORTAS_SCRIPT,
  ROTULO_BLOCO,
  type BlocoNode,
  type DadosTfs,
  type NoEscrita,
  type NoLeitura,
  type NoScript,
} from "../graph";
import { inteiroDoCampo, matrizDoFormulario } from "./campos";
import { CamposTfs } from "./CamposTfs";

const OPCOES_PORTAS = Array.from({ length: MAX_PORTAS_SCRIPT + 1 }, (_, i) => i);

function CamposTag({
  dados,
  direcao,
  tags,
}: {
  dados: NoLeitura["data"] | NoEscrita["data"];
  direcao: "r" | "w";
  tags: readonly TagOut[];
}) {
  // Seletor filtrado por direção e pelo projeto ativo (a lista já chega recortada por projeto).
  const disponiveis = tags.filter((tag) => tag.direction === direcao);
  return (
    <div className="space-y-1">
      <Label htmlFor="tag_id">Tag</Label>
      <Select id="tag_id" name="tag_id" data-testid="config-tag" defaultValue={dados.tag_id ?? ""}>
        <option value="">Selecione uma tag…</option>
        {disponiveis.map((tag) => (
          <option key={tag.id} value={tag.id}>
            {tag.name} · {ROTULO_TIPO[tag.data_type]}
            {tag.eu ? ` · ${tag.eu}` : ""}
          </option>
        ))}
      </Select>
      {disponiveis.length === 0 && (
        <p className="text-xs text-warn">
          Nenhuma tag de {direcao === "r" ? "leitura" : "escrita"} cadastrada no projeto ativo.
        </p>
      )}
    </div>
  );
}

/** Tab indenta em vez de sair do campo (spec F3 §6.2: sem editor de código de terceiros). */
function indentarComTab(evento: KeyboardEvent<HTMLTextAreaElement>): void {
  if (evento.key !== "Tab" || evento.shiftKey || evento.ctrlKey || evento.altKey || evento.metaKey) {
    return;
  }
  evento.preventDefault();
  const campo = evento.currentTarget;
  campo.setRangeText("    ", campo.selectionStart, campo.selectionEnd, "end");
}

function CamposScript({ dados }: { dados: NoScript["data"] }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="n_inputs">Entradas (IN1..INn)</Label>
          <Select id="n_inputs" name="n_inputs" data-testid="config-n-inputs" defaultValue={dados.n_inputs}>
            {OPCOES_PORTAS.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="n_outputs">Saídas (OUT1..OUTn)</Label>
          <Select id="n_outputs" name="n_outputs" data-testid="config-n-outputs" defaultValue={dados.n_outputs}>
            {OPCOES_PORTAS.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="code">Código</Label>
        <textarea
          id="code"
          name="code"
          data-testid="config-code"
          rows={12}
          spellCheck={false}
          defaultValue={dados.code}
          onKeyDown={indentarComTab}
          className="w-full rounded-panel border border-hairline bg-well p-2 font-mono text-xs leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
        />
        <p className="text-[10px] text-fg-muted">
          Escopo disponível: IN1..INn, state, math, numpy (np). Tab insere quatro espaços; Esc
          fecha o modal.
        </p>
      </div>
    </div>
  );
}

interface Props {
  no: BlocoNode;
  /** Total de blocos no canvas: teto do `exec_order` (contíguo 1..N, ADR-024). */
  totalBlocos: number;
  tags: readonly TagOut[];
  podeMutar: boolean;
  onAplicar: (no: BlocoNode, execOrder: number) => void;
  onFechar: () => void;
}

/**
 * Modal de config por duplo-clique (RF-301), um formulário por tipo de bloco.
 *
 * Os campos são não-controlados e lidos no envio; só `enabled`/`kind` da matriz do TFS vivem
 * em estado, porque decidem quais parâmetros existem. Para o operador o `fieldset` inteiro
 * entra desabilitado (contrato de RBAC, PRD §2).
 */
export function ModalConfigBloco({
  no,
  totalBlocos,
  tags,
  podeMutar,
  onAplicar,
  onFechar,
}: Props) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [matrizTfs, setMatrizTfs] = useState<DadosTfs | null>(no.type === "tfs" ? no.data : null);

  useEffect(() => {
    dialogo.current?.showModal();
  }, []);

  function aplicar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const campos = new FormData(evento.currentTarget);
    const label = String(campos.get("label") ?? "").trim();
    const execOrder = inteiroDoCampo(campos.get("exec_order"), no.data.exec_order, 1, totalBlocos);

    switch (no.type) {
      case "opc_read":
      case "opc_write": {
        const bruto = String(campos.get("tag_id") ?? "");
        const tag_id = bruto === "" ? null : Number(bruto);
        onAplicar({ ...no, data: { ...no.data, label, tag_id } }, execOrder);
        break;
      }
      case "script":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              n_inputs: inteiroDoCampo(campos.get("n_inputs"), 0, 0, MAX_PORTAS_SCRIPT),
              n_outputs: inteiroDoCampo(campos.get("n_outputs"), 0, 0, MAX_PORTAS_SCRIPT),
              code: String(campos.get("code") ?? ""),
            },
          },
          execOrder,
        );
        break;
      case "tfs":
        onAplicar(
          {
            ...no,
            data: {
              ...no.data,
              label,
              matrix: matrizDoFormulario((matrizTfs ?? no.data).matrix, campos),
            },
          },
          execOrder,
        );
        break;
    }
    onFechar();
  }

  return (
    <dialog
      ref={dialogo}
      onClose={onFechar}
      data-testid="config-modal"
      className="modal-bloco max-h-[85vh] w-[min(760px,92vw)] overflow-auto rounded-panel border border-hairline bg-panel p-0 text-fg"
    >
      <form onSubmit={aplicar}>
        <header className="flex items-center justify-between border-b border-hairline bg-well px-4 py-3">
          <h2 className="plaqueta text-sm text-fg">Configurar {ROTULO_BLOCO[no.type]}</h2>
          <span className="process-value text-xs text-fg-muted">{no.id}</span>
        </header>

        <fieldset disabled={!podeMutar} className="space-y-4 p-4">
          {!podeMutar && (
            <p className="text-xs text-fg-muted">
              Somente leitura: a edição do flow é do papel admin.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="label">Rótulo</Label>
              <Input
                id="label"
                name="label"
                data-testid="config-label"
                maxLength={60}
                defaultValue={no.data.label}
                placeholder={ROTULO_BLOCO[no.type]}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="exec_order">Ordem de execução</Label>
              <Input
                id="exec_order"
                name="exec_order"
                data-testid="config-exec-order"
                type="number"
                min={1}
                max={totalBlocos}
                className="process-value"
                defaultValue={no.data.exec_order}
              />
              <p className="text-[10px] text-fg-muted">
                Contígua de 1 a {totalBlocos}; os demais blocos deslizam para acomodar.
              </p>
            </div>
          </div>

          {no.type === "opc_read" && <CamposTag dados={no.data} direcao="r" tags={tags} />}
          {no.type === "opc_write" && <CamposTag dados={no.data} direcao="w" tags={tags} />}
          {no.type === "script" && <CamposScript dados={no.data} />}
          {no.type === "tfs" && matrizTfs !== null && (
            <CamposTfs dados={matrizTfs} aoMudar={setMatrizTfs} />
          )}
        </fieldset>

        <footer className="flex justify-end gap-2 border-t border-hairline px-4 py-3">
          <Button
            type="button"
            variant="outline"
            data-testid="config-cancelar"
            onClick={() => dialogo.current?.close()}
          >
            {podeMutar ? "Cancelar" : "Fechar"}
          </Button>
          {podeMutar && (
            <Button type="submit" data-testid="config-aplicar">
              Aplicar
            </Button>
          )}
        </footer>
      </form>
    </dialog>
  );
}
