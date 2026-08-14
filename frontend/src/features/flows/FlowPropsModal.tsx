import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError, type FlowDetail } from "../../lib/api";
import { useConnections } from "../connections/useConnections";
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
 * Diálogo de propriedades do flow (RF-30x, spec F3, tarefa 3.1; watchdog por flow, ADR-009
 * revisado): Nome, Ts e watchdog editáveis; projeto e estado desejado somente leitura.
 * `graph_json` nunca entra no PUT deste modal — o grafo em edição não é tocado (contrato 0.3:
 * campo ausente mantém o grafo salvo). Os cinco campos de watchdog sempre viajam juntos no
 * corpo do PUT quando o diálogo salva (mesma convenção de `FlowUpdate`: campo ausente mantém
 * o valor gravado, mas este diálogo é o único lugar onde o operador os edita).
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
  const [watchdogEnabled, setWatchdogEnabled] = useState(flow.watchdog_enabled);
  const [watchdogConnectionId, setWatchdogConnectionId] = useState<number | null>(
    flow.watchdog_connection_id ?? null,
  );
  const [watchdogReadNodeId, setWatchdogReadNodeId] = useState(flow.watchdog_read_node_id ?? "");
  const [watchdogWriteNodeId, setWatchdogWriteNodeId] = useState(
    flow.watchdog_write_node_id ?? "",
  );
  const [watchdogPeriodMs, setWatchdogPeriodMs] = useState(String(flow.watchdog_period_ms));
  const [watchdogTimeoutS, setWatchdogTimeoutS] = useState(String(flow.watchdog_timeout_s));
  // Conexões do próprio projeto do flow (mesmo hook de `ConnectionsPage.tsx`) — o backend
  // recusa `watchdog_connection_id` de outro projeto (422, `erro_watchdog_flow`-adjacent), o
  // seletor já restringe a esse universo.
  const conexoes = useConnections(flow.project_id);

  // `main.tsx` monta sob <StrictMode>: em dev o efeito roda duas vezes e `showModal()` num
  // <dialog> já aberto levanta InvalidStateError (mesma nota dos outros modais do editor).
  useEffect(() => {
    const elemento = dialogo.current;
    if (elemento !== null && !elemento.open) elemento.showModal();
  }, []);

  const tsMudou = ts !== flow.ts_seconds;
  const precisaConfirmar = tsMudou && flow.desired_state === "running";

  /** Espelho de `erro_watchdog_flow` (schemas/flows.py): habilitado exige conexão e os dois
   *  node_ids, distintos entre si — quem inverte o bit é o DCS/PLC, não o ottima. */
  function erroWatchdog(): string | null {
    if (!watchdogEnabled) return null;
    const leitura = watchdogReadNodeId.trim();
    const escrita = watchdogWriteNodeId.trim();
    if (watchdogConnectionId === null || !leitura || !escrita) {
      return "Watchdog habilitado exige conexão e os dois node_ids (leitura e escrita)";
    }
    if (leitura === escrita) {
      return "Watchdog exige node_ids de leitura e escrita distintos";
    }
    const periodo = Number(watchdogPeriodMs);
    if (!Number.isInteger(periodo) || periodo < 500 || periodo > 5000) {
      return "Período do watchdog deve ser um número inteiro entre 500 e 5000 ms";
    }
    const timeout = Number(watchdogTimeoutS);
    if (Number.isInteger(timeout) && timeout * 1000 < 2 * periodo) {
      return "timeout do watchdog deve ser ao menos 2x o período";
    }
    if (!Number.isInteger(timeout) || timeout < 2 || timeout > 120) {
      return "Timeout do watchdog deve ser um número inteiro entre 2 e 120 s";
    }
    return null;
  }

  async function aplicar(): Promise<void> {
    setErro(null);
    const erroLocal = erroWatchdog();
    if (erroLocal !== null) {
      setErro(erroLocal);
      return;
    }
    try {
      await salvar.mutateAsync({
        name: nome.trim(),
        ts_seconds: ts,
        watchdog_enabled: watchdogEnabled,
        watchdog_connection_id: watchdogEnabled ? watchdogConnectionId : null,
        watchdog_read_node_id: watchdogEnabled ? watchdogReadNodeId.trim() : null,
        watchdog_write_node_id: watchdogEnabled ? watchdogWriteNodeId.trim() : null,
        watchdog_period_ms: Number(watchdogPeriodMs),
        watchdog_timeout_s: Number(watchdogTimeoutS),
      });
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
      className="modal-bloco w-[min(480px,92vw)] overflow-auto rounded-sm border border-border bg-surface p-0 text-fg"
    >
      <form onSubmit={aoSubmeter}>
        <header className="flex items-center justify-between border-b border-border bg-well px-4 py-3">
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

          <div className="space-y-3 border-t border-border pt-4">
            <label className="flex items-center gap-2 text-xs text-fg">
              <input
                type="checkbox"
                id="flow-props-wd-enabled"
                data-testid="flow-props-wd-enabled"
                checked={watchdogEnabled}
                onChange={(evento) => setWatchdogEnabled(evento.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-accent)]"
              />
              Watchdog (ADR-009) — sem ele o flow fica somente leitura
            </label>

            {watchdogEnabled && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="flow-props-wd-connection">Conexão</Label>
                  <Select
                    id="flow-props-wd-connection"
                    data-testid="flow-props-wd-connection"
                    value={watchdogConnectionId === null ? "" : String(watchdogConnectionId)}
                    onChange={(evento) => {
                      const valor = evento.target.value;
                      setWatchdogConnectionId(valor === "" ? null : Number(valor));
                    }}
                  >
                    <option value="">Selecione…</option>
                    {(conexoes.data ?? []).map((conexao) => (
                      <option key={conexao.id} value={String(conexao.id)}>
                        {conexao.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="flow-props-wd-read">Node de leitura (watchdogB)</Label>
                    <Input
                      id="flow-props-wd-read"
                      data-testid="flow-props-wd-read"
                      className="process-value"
                      placeholder="ns=2;s=..."
                      value={watchdogReadNodeId}
                      onChange={(evento) => setWatchdogReadNodeId(evento.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="flow-props-wd-write">Node de escrita (watchdogA)</Label>
                    <Input
                      id="flow-props-wd-write"
                      data-testid="flow-props-wd-write"
                      className="process-value"
                      placeholder="ns=2;s=..."
                      value={watchdogWriteNodeId}
                      onChange={(evento) => setWatchdogWriteNodeId(evento.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="flow-props-wd-period">Período (ms)</Label>
                    <Input
                      id="flow-props-wd-period"
                      data-testid="flow-props-wd-period"
                      className="process-value"
                      type="number"
                      min={500}
                      max={5000}
                      step={100}
                      value={watchdogPeriodMs}
                      onChange={(evento) => setWatchdogPeriodMs(evento.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="flow-props-wd-timeout">Timeout (s)</Label>
                    <Input
                      id="flow-props-wd-timeout"
                      data-testid="flow-props-wd-timeout"
                      className="process-value"
                      type="number"
                      min={2}
                      max={120}
                      step={1}
                      value={watchdogTimeoutS}
                      onChange={(evento) => setWatchdogTimeoutS(evento.target.value)}
                    />
                  </div>
                </div>
              </div>
            )}
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

        <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">
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
