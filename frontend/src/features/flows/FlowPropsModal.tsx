import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError, type FlowDetail } from "../../lib/api";
import { formatarTs, ROTULO_DESEJADO, TS_OPCOES, useSalvarPropriedades, type TsSegundos } from "./useFlows";

function erroLegivel(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

const AVISO_REINICIO =
  "Alterar o Ts reinicia todos os blocos do flow: o MPC voltará a LOCAL (a MV segue o readback).";

interface Props {
  flow: FlowDetail;
  onFechar: () => void;
}

/**
 * Diálogo de propriedades do flow (RF-30x, spec F3, tarefa 3.1): Nome e Ts editáveis;
 * projeto e estado desejado somente leitura. `graph_json` nunca entra no PUT deste modal —
 * o grafo em edição não é tocado (contrato 0.3: campo ausente mantém o grafo salvo).
 *
 * Mesmo molde de `<dialog>` nativo dos modais de bloco (`MpcModal.tsx`/`ModalConfigBloco.tsx`):
 * foco preso e Esc de graça do elemento nativo, `.modal-bloco` já carregado por
 * `flow-canvas.css` (import da própria `FlowEditorPage.tsx`).
 */
export function FlowPropsModal({ flow, onFechar }: Props) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const salvar = useSalvarPropriedades(flow.id);
  const [nome, setNome] = useState(flow.name);
  const [ts, setTs] = useState<TsSegundos>(flow.ts_seconds as TsSegundos);
  const [confirmando, setConfirmando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // `main.tsx` monta sob <StrictMode>: em dev o efeito roda duas vezes e `showModal()` num
  // <dialog> já aberto levanta InvalidStateError (mesma nota dos outros modais do editor).
  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) elemento.showModal();
  }, []);

  const tsMudou = ts !== flow.ts_seconds;
  const precisaConfirmar = tsMudou && flow.desired_state === "running";

  async function aplicar(): Promise<void> {
    setErro(null);
    try {
      await salvar.mutateAsync({ name: nome.trim(), ts_seconds: ts });
      dialogo.current?.close();
    } catch (err) {
      setErro(erroLegivel(err));
    }
  }

  function aoSubmeter(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    if (precisaConfirmar && !confirmando) {
      setConfirmando(true);
      return;
    }
    void aplicar();
  }

  return (
    <dialog
      ref={dialogo}
      onClose={onFechar}
      data-testid="flow-props-modal"
      className="modal-bloco w-[min(480px,92vw)] overflow-auto rounded-panel border border-hairline bg-panel p-0 text-fg"
    >
      <form onSubmit={aoSubmeter}>
        <header className="flex items-center justify-between border-b border-hairline bg-well px-4 py-3">
          <h2 className="plaqueta text-sm text-fg">Propriedades do flow</h2>
        </header>

        <div className="space-y-4 p-4">
          <div className="space-y-1">
            <Label htmlFor="flow-props-nome-campo">Nome</Label>
            <Input
              id="flow-props-nome-campo"
              data-testid="flow-props-nome"
              value={nome}
              onChange={(evento) => {
                setNome(evento.target.value);
                setConfirmando(false);
              }}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="flow-props-ts-campo">Ts (s)</Label>
            <Select
              id="flow-props-ts-campo"
              data-testid="flow-props-ts"
              className="process-value"
              value={String(ts)}
              onChange={(evento) => {
                setTs(Number(evento.target.value) as TsSegundos);
                setConfirmando(false);
              }}
            >
              {TS_OPCOES.map((opcao) => (
                <option key={opcao} value={String(opcao)}>
                  {formatarTs(opcao)}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="space-y-1">
              <p className="plaqueta text-fg-muted">Projeto</p>
              <p className="process-value text-fg">{flow.project_id}</p>
            </div>
            <div className="space-y-1">
              <p className="plaqueta text-fg-muted">Estado desejado</p>
              <p className="text-fg">{ROTULO_DESEJADO[flow.desired_state]}</p>
            </div>
          </div>

          {confirmando && (
            <p role="alert" data-testid="flow-props-aviso" className="text-xs text-alarm">
              {AVISO_REINICIO}
            </p>
          )}
          {erro !== null && (
            <p role="alert" data-testid="flow-props-erro" className="text-xs text-alarm">
              {erro}
            </p>
          )}
        </div>

        <footer className="flex justify-end gap-2 border-t border-hairline px-4 py-3">
          {confirmando ? (
            <>
              <Button
                type="button"
                variant="outline"
                data-testid="flow-props-cancelar"
                onClick={() => {
                  setConfirmando(false);
                }}
              >
                Cancelar
              </Button>
              <Button
                type="button"
                data-testid="flow-props-confirmar"
                disabled={salvar.isPending}
                onClick={() => void aplicar()}
              >
                {salvar.isPending ? "Aplicando…" : "Confirmar"}
              </Button>
            </>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                data-testid="flow-props-fechar"
                onClick={() => dialogo.current?.close()}
              >
                Cancelar
              </Button>
              <Button type="submit" data-testid="flow-props-aplicar" disabled={salvar.isPending}>
                {salvar.isPending ? "Aplicando…" : "Aplicar"}
              </Button>
            </>
          )}
        </footer>
      </form>
    </dialog>
  );
}
