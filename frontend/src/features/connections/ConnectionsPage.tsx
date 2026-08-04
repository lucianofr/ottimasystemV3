import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ApiError, type ConnectionOut } from "../../lib/api";
import { useCanMutate } from "../auth/useAuth";
import { ConnectionForm } from "./ConnectionForm";
import { useActiveProject, useConnections, useDeleteConnection } from "./useConnections";
import { useLastConnectionState, type UltimoEstado } from "./useLastConnectionState";

const POLICY: Record<ConnectionOut["security_policy"], string> = {
  none: "Sem segurança",
  basic256sha256: "Basic256Sha256",
};

const MODE: Record<ConnectionOut["security_mode"], string> = {
  none: "Nenhum",
  sign: "Assinar",
  sign_and_encrypt: "Assinar e cifrar",
};

const AUTH: Record<ConnectionOut["auth_mode"], string> = {
  anonymous: "Anônima",
  user_password: "Usuário/senha",
  certificate: "Certificado",
};

function rotuloSeguranca(conexao: ConnectionOut): string {
  if (conexao.security_policy === "none") return POLICY.none;
  return `${POLICY[conexao.security_policy]} · ${MODE[conexao.security_mode]}`;
}

const COLUNAS = [
  "Nome",
  "Endpoint",
  "Segurança",
  "Autenticação",
  "Watchdog",
  "Senha",
  "Último estado",
] as const;

/** Watchdog só existe com o par de node_ids; sem ele a conexão é somente leitura (§3.5). */
function CelulaWatchdog({ conexao }: { conexao: ConnectionOut }) {
  const configurado =
    conexao.watchdog_read_node_id !== null && conexao.watchdog_write_node_id !== null;
  if (!configurado) {
    return (
      <span className="text-fg-muted">
        — <span className="ml-1 text-xs">somente leitura</span>
      </span>
    );
  }
  return (
    <span>
      <span className="process-value">{conexao.watchdog_period_ms}</span>{" "}
      <span className="text-xs text-fg-muted">ms</span>
    </span>
  );
}

function CelulaUltimoEstado({ estado }: { estado: UltimoEstado | undefined }) {
  if (!estado) {
    return (
      <span data-testid="conn-last-state" className="text-fg-muted">
        —
      </span>
    );
  }
  if (!estado.falha) {
    return <span data-testid="conn-last-state">{estado.rotulo}</span>;
  }
  // Regra do Canal Redundante: cor + ícone + texto (DESIGN.md §Colors)
  return (
    <span data-testid="conn-last-state" className="flex items-center gap-1.5 text-alarm">
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

export function ConnectionsPage() {
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;
  const conexoes = useConnections(projectId);
  const estados = useLastConnectionState();
  const excluir = useDeleteConnection();
  const [formAberto, setFormAberto] = useState(false);
  const [emEdicao, setEmEdicao] = useState<ConnectionOut | null>(null);
  const [aConfirmar, setAConfirmar] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  function abrirCriacao(): void {
    setEmEdicao(null);
    setAConfirmar(null);
    setErro(null);
    setFormAberto(true);
  }

  function abrirEdicao(conexao: ConnectionOut): void {
    setEmEdicao(conexao);
    setAConfirmar(null);
    setErro(null);
    setFormAberto(true);
  }

  async function confirmarExclusao(id: number): Promise<void> {
    setErro(null);
    try {
      await excluir.mutateAsync(id);
      setAConfirmar(null);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    }
  }

  const podeMutar = useCanMutate();
  const linhas = conexoes.data ?? [];
  const totalColunas = COLUNAS.length + (podeMutar ? 1 : 0);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Conexões</h1>
        {podeMutar && (
          <Button data-testid="conn-new" onClick={abrirCriacao} disabled={projectId === null}>
            Nova conexão
          </Button>
        )}
      </div>

      {podeMutar && formAberto && projectId !== null && (
        <ConnectionForm
          key={emEdicao?.id ?? "nova"}
          conexao={emEdicao}
          projectId={projectId}
          onClose={() => setFormAberto(false)}
        />
      )}

      {erro && (
        <p role="alert" data-testid="conn-error" className="text-sm text-alarm">
          {erro}
        </p>
      )}

      {/* Tabela em chapa: bg-panel, hairline, cabeçalho em plaqueta (DESIGN.md §Elevation) */}
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
                  Nenhum projeto ativo: ative um projeto para cadastrar conexões.
                </td>
              </tr>
            )}
            {conexoes.isPending && projectId !== null && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {conexoes.isError && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar conexões
                </td>
              </tr>
            )}
            {conexoes.isSuccess && linhas.length === 0 && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Nenhuma conexão cadastrada
                </td>
              </tr>
            )}
            {linhas.map((conexao) => (
              <tr key={conexao.id} data-testid="conn-row" className="border-b border-hairline">
                <td className="px-3 py-2">{conexao.name}</td>
                <td className="process-value px-3 py-2">{conexao.endpoint}</td>
                <td className="px-3 py-2">{rotuloSeguranca(conexao)}</td>
                <td className="px-3 py-2">{AUTH[conexao.auth_mode]}</td>
                <td className="px-3 py-2">
                  <CelulaWatchdog conexao={conexao} />
                </td>
                <td className="px-3 py-2">
                  {conexao.has_password ? "definida" : <span className="text-fg-muted">—</span>}
                </td>
                <td className="px-3 py-2">
                  <CelulaUltimoEstado estado={estados.get(conexao.id)} />
                </td>
                {podeMutar && (
                  <td className="px-3 py-2">
                    {aConfirmar === conexao.id ? (
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-xs text-fg-muted">Excluir esta conexão?</span>
                        <Button
                          variant="destructive"
                          size="sm"
                          data-testid="conn-delete-confirm"
                          disabled={excluir.isPending}
                          onClick={() => void confirmarExclusao(conexao.id)}
                        >
                          Confirmar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="conn-delete-cancel"
                          onClick={() => setAConfirmar(null)}
                        >
                          Cancelar
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="conn-edit"
                          onClick={() => abrirEdicao(conexao)}
                        >
                          Editar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="conn-delete"
                          onClick={() => {
                            setErro(null);
                            setAConfirmar(conexao.id);
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
