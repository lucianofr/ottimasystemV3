import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError, type FlowOut } from "../../lib/api";
import { useCanMutate } from "../auth/useAuth";
import { useActiveProject } from "../connections/useConnections";
import {
  formatarTs,
  ROTULO_DESEJADO,
  TS_OPCOES,
  useComandarFlow,
  useCreateFlow,
  useDeleteFlow,
  useFlows,
  type TsSegundos,
} from "./useFlows";
import {
  aguardandoConfirmacao,
  useLastFlowState,
  type UltimoEstadoFlow,
} from "./useLastFlowState";

/** "Desejado" (banco) e "Último estado" (runtime) são colunas distintas e nunca se fundem —
 *  Regra do Estado Publicado (DESIGN.md). Esta tela é onde a divergência fica visível. */
const COLUNAS = ["Nome", "Ts", "Desejado", "Último estado"] as const;

const TS_PADRAO: TsSegundos = 1;

function erroLegivel(err: unknown): string {
  return err instanceof ApiError ? err.message : "Erro de comunicação com o servidor";
}

function FlowForm({ projectId, onClose }: { projectId: number; onClose: () => void }) {
  const [nome, setNome] = useState("");
  const [ts, setTs] = useState<TsSegundos>(TS_PADRAO);
  const [erro, setErro] = useState<string | null>(null);
  const criar = useCreateFlow();

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    if (!nome.trim()) {
      setErro("Nome é obrigatório");
      return;
    }
    setErro(null);
    try {
      await criar.mutateAsync({ project_id: projectId, name: nome.trim(), ts_seconds: ts });
      onClose();
    } catch (err) {
      setErro(erroLegivel(err));
    }
  }

  return (
    <Card className="p-6">
      <h2 className="plaqueta text-xs text-fg-muted">Novo flow</h2>
      <form
        data-testid="flow-form"
        onSubmit={(e) => void onSubmit(e)}
        className="mt-4 space-y-6"
        noValidate
      >
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="flow-name">Nome</Label>
            <Input
              id="flow-name"
              data-testid="flow-name"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="flow-ts">Ts (s)</Label>
            <Select
              id="flow-ts"
              data-testid="flow-ts"
              className="process-value"
              value={String(ts)}
              onChange={(e) => setTs(Number(e.target.value) as TsSegundos)}
            >
              {TS_OPCOES.map((opcao) => (
                <option key={opcao} value={String(opcao)}>
                  {formatarTs(opcao)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {erro && (
          <p role="alert" data-testid="flow-form-error" className="text-sm text-alarm">
            {erro}
          </p>
        )}

        <div className="flex items-center gap-2 border-t border-hairline pt-4">
          <Button type="submit" data-testid="flow-submit" disabled={criar.isPending}>
            Criar
          </Button>
          <Button type="button" variant="outline" data-testid="flow-cancel" onClick={onClose}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}

/** Comandado pendente: contorno de acento + o valor comandado em fantasma, com rótulo textual
 *  (Regra do Canal Redundante — cor nunca é o único canal). */
function CelulaDesejado({
  flow,
  publicado,
}: {
  flow: FlowOut;
  publicado: UltimoEstadoFlow | undefined;
}) {
  const rotulo = ROTULO_DESEJADO[flow.desired_state];
  if (!aguardandoConfirmacao(flow.desired_state, publicado)) {
    return <span data-testid="flow-desired">{rotulo}</span>;
  }
  return (
    <span
      data-testid="flow-desired"
      className="inline-flex items-center gap-1.5 rounded-panel border border-accent px-1.5 py-0.5 text-fg-muted"
    >
      {rotulo}
      <span className="text-xs">aguardando confirmação</span>
    </span>
  );
}

function CelulaUltimoEstado({ estado }: { estado: UltimoEstadoFlow | undefined }) {
  if (!estado) {
    return (
      <span data-testid="flow-last-state" className="text-fg-muted">
        —
      </span>
    );
  }
  if (!estado.falha) {
    return <span data-testid="flow-last-state">{estado.rotulo}</span>;
  }
  return (
    <span data-testid="flow-last-state" className="flex items-center gap-1.5 text-alarm">
      <svg
        aria-hidden="true"
        width="12"
        height="12"
        viewBox="0 0 16 16"
        fill="currentColor"
        className="shrink-0"
      >
        <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
      </svg>
      {estado.rotulo}
    </span>
  );
}

export function FlowsPage() {
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;
  const flows = useFlows(projectId);
  const estados = useLastFlowState();
  const excluir = useDeleteFlow();
  const deploy = useComandarFlow("deploy");
  const parar = useComandarFlow("stop");
  const [formAberto, setFormAberto] = useState(false);
  const [aConfirmar, setAConfirmar] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  /** Deploy e Parar são intenção (202): o sucesso aqui só confirma que o comando foi aceito
   *  e o desejado gravado. Quem confirma o efeito é a coluna "Último estado". */
  async function comandar(promessa: Promise<void>): Promise<void> {
    setErro(null);
    try {
      await promessa;
    } catch (err) {
      setErro(erroLegivel(err));
    }
  }

  async function confirmarExclusao(id: number): Promise<void> {
    setErro(null);
    try {
      await excluir.mutateAsync(id);
      setAConfirmar(null);
    } catch (err) {
      // 409 do flow rodando chega como `detail` string da API (spec F3 §5.1).
      setErro(erroLegivel(err));
    }
  }

  const podeMutar = useCanMutate();
  const linhas = flows.data ?? [];
  const totalColunas = COLUNAS.length + (podeMutar ? 1 : 0);
  const comandando = deploy.isPending || parar.isPending;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Flows</h1>
        {podeMutar && (
          <Button
            data-testid="flow-new"
            onClick={() => {
              setAConfirmar(null);
              setErro(null);
              setFormAberto(true);
            }}
            disabled={projectId === null}
          >
            Novo flow
          </Button>
        )}
      </div>

      {podeMutar && formAberto && projectId !== null && (
        <FlowForm projectId={projectId} onClose={() => setFormAberto(false)} />
      )}

      {erro && (
        <p role="alert" data-testid="flow-error" className="text-sm text-alarm">
          {erro}
        </p>
      )}

      <Card className="overflow-hidden">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-hairline">
              {COLUNAS.map((coluna) => (
                <th key={coluna} className="plaqueta px-3 py-2 text-left text-xs text-fg-muted">
                  {coluna}
                </th>
              ))}
              {podeMutar && (
                <th className="px-3 py-2">
                  <span className="sr-only">Ações</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {projeto.isSuccess && projectId === null && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Nenhum projeto ativo: ative um projeto para cadastrar flows.
                </td>
              </tr>
            )}
            {flows.isPending && projectId !== null && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {flows.isError && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar flows
                </td>
              </tr>
            )}
            {flows.isSuccess && linhas.length === 0 && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Nenhum flow cadastrado
                </td>
              </tr>
            )}
            {linhas.map((flow) => (
              <tr key={flow.id} data-testid="flow-row" className="border-b border-hairline">
                <td className="px-3 py-2">{flow.name}</td>
                <td className="px-3 py-2">
                  <span className="process-value">{formatarTs(flow.ts_seconds)}</span>{" "}
                  <span className="text-xs text-fg-muted">s</span>
                </td>
                <td className="px-3 py-2">
                  <CelulaDesejado flow={flow} publicado={estados.get(flow.id)} />
                </td>
                <td className="px-3 py-2">
                  <CelulaUltimoEstado estado={estados.get(flow.id)} />
                </td>
                {podeMutar && (
                  <td className="px-3 py-2">
                    {aConfirmar === flow.id ? (
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-xs text-fg-muted">Excluir este flow?</span>
                        <Button
                          variant="destructive"
                          size="sm"
                          data-testid="flow-delete-confirm"
                          disabled={excluir.isPending}
                          onClick={() => void confirmarExclusao(flow.id)}
                        >
                          Confirmar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="flow-delete-cancel"
                          onClick={() => setAConfirmar(null)}
                        >
                          Cancelar
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        {/* Os dois comandos ficam sempre disponíveis: divergência entre desejado
                            e publicado só se resolve o operador recomandando (ADR-017). */}
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="flow-deploy"
                          disabled={comandando}
                          onClick={() => void comandar(deploy.mutateAsync(flow.id))}
                        >
                          Deploy
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="flow-stop"
                          disabled={comandando}
                          onClick={() => void comandar(parar.mutateAsync(flow.id))}
                        >
                          Parar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="flow-delete"
                          onClick={() => {
                            setErro(null);
                            setAConfirmar(flow.id);
                          }}
                        >
                          Excluir
                        </Button>
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}
