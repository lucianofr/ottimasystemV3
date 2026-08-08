import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ApiError, type ProjectOut } from "../../lib/api";
import { baixarArquivo } from "../../lib/arquivos";
import { useCanMutate } from "../auth/useAuth";
import { ConfirmarAtivacao } from "./ConfirmarAtivacao";
import { nomeArquivoExportado } from "./nomeArquivoExportado";
import { ProjectForm } from "./ProjectForm";
import { useDeleteProject, useProjects } from "./useProjects";

const COLUNAS = ["Nome", "Descrição", "Ativo"] as const;

/** "Ativo" é seleção de configuração, não execução — Azul Industrial, nunca Verde Rodando
 *  (DESIGN.md §Colors; spec §6.1-2, UX-10). Ícone + rótulo, nunca só cor (Regra do Canal
 *  Redundante). */
function CelulaAtivo({ ativo }: { ativo: boolean }) {
  if (!ativo) {
    return <span className="text-fg-muted">—</span>;
  }
  return (
    <span className="flex items-center gap-1.5 text-accent">
      <svg
        aria-hidden="true"
        width="10"
        height="10"
        viewBox="0 0 16 16"
        fill="currentColor"
        className="shrink-0"
      >
        <circle cx="8" cy="8" r="6" />
      </svg>
      Ativo
    </span>
  );
}

export function ProjectsPage() {
  const projetos = useProjects();
  const excluir = useDeleteProject();
  const [formAberto, setFormAberto] = useState(false);
  const [emEdicao, setEmEdicao] = useState<ProjectOut | null>(null);
  const [aConfirmar, setAConfirmar] = useState<number | null>(null);
  const [ativarAlvo, setAtivarAlvo] = useState<ProjectOut | null>(null);
  const [exportando, setExportando] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  function abrirCriacao(): void {
    setEmEdicao(null);
    setAConfirmar(null);
    setAtivarAlvo(null);
    setErro(null);
    setFormAberto(true);
  }

  function abrirEdicao(projeto: ProjectOut): void {
    setEmEdicao(projeto);
    setAConfirmar(null);
    setAtivarAlvo(null);
    setErro(null);
    setFormAberto(true);
  }

  async function confirmarExclusao(id: number): Promise<void> {
    setErro(null);
    try {
      await excluir.mutateAsync(id);
      setAConfirmar(null);
    } catch (err) {
      // Excluir o projeto ativo é recusado pelo servidor com 409 (spec §6.1-3, projects.py:67-74);
      // a tela exibe a recusa verbatim, sem duplicar a regra no cliente.
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    }
  }

  async function exportarProjeto(projeto: ProjectOut): Promise<void> {
    setErro(null);
    setExportando(projeto.id);
    try {
      await baixarArquivo(
        `/api/projects/${String(projeto.id)}/export`,
        nomeArquivoExportado(projeto.name),
      );
    } catch (err) {
      // Mesmo padrão de confirmarExclusao/ConfirmarAtivacao: 404 (projeto sumiu) ou 422
      // (referência de tag irresolvível) chegam com `detail` pt-BR do servidor e são
      // exibidos verbatim, nunca substituídos por mensagem genérica (spec §6.1-5).
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    } finally {
      setExportando(null);
    }
  }

  const podeMutar = useCanMutate();
  const linhas = projetos.data ?? [];
  const totalColunas = COLUNAS.length + (podeMutar ? 1 : 0);
  const vazio = projetos.isSuccess && linhas.length === 0;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Projetos</h1>
        {podeMutar && (
          <Button data-testid="proj-new" onClick={abrirCriacao}>
            Novo projeto
          </Button>
        )}
      </div>

      {podeMutar && formAberto && (
        <ProjectForm
          key={emEdicao?.id ?? "nova"}
          projeto={emEdicao}
          onClose={() => setFormAberto(false)}
        />
      )}

      {erro && (
        <p role="alert" data-testid="proj-error" className="text-sm text-alarm">
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
            {projetos.isPending && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {projetos.isError && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar projetos
                </td>
              </tr>
            )}
            {vazio && (
              // Dia 1 de instalação: estado próprio com os dois caminhos possíveis (spec
              // §6.1-7, UX-09). "Criar" é o botão acima; "importar" chega na tarefa 2.4 —
              // aqui só o texto que a anuncia, sem lógica nenhuma de importação.
              <tr>
                <td colSpan={totalColunas} className="px-3 py-6 text-center">
                  <p className="text-fg-muted">Nenhum projeto cadastrado</p>
                  {podeMutar && (
                    <p className="mt-2 text-xs text-fg-muted">
                      Crie um novo projeto ou importe um arquivo de projeto existente.
                    </p>
                  )}
                </td>
              </tr>
            )}
            {linhas.map((projeto) => (
              <tr
                key={projeto.id}
                data-testid="proj-row"
                data-proj-id={projeto.id}
                className="border-b border-hairline"
              >
                <td className="px-3 py-2">{projeto.name}</td>
                <td className="px-3 py-2">
                  {projeto.description || <span className="text-fg-muted">—</span>}
                </td>
                <td className="px-3 py-2">
                  <CelulaAtivo ativo={projeto.is_active} />
                </td>
                {podeMutar && (
                  <td className="px-3 py-2">
                    {aConfirmar === projeto.id ? (
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-xs text-fg-muted">Excluir este projeto?</span>
                        <Button
                          variant="destructive"
                          size="sm"
                          data-testid="proj-delete-confirm"
                          disabled={excluir.isPending}
                          onClick={() => void confirmarExclusao(projeto.id)}
                        >
                          Confirmar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="proj-delete-cancel"
                          onClick={() => setAConfirmar(null)}
                        >
                          Cancelar
                        </Button>
                      </div>
                    ) : ativarAlvo?.id === projeto.id ? (
                      <ConfirmarAtivacao alvo={projeto} onCancelar={() => setAtivarAlvo(null)} />
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="proj-edit"
                          onClick={() => abrirEdicao(projeto)}
                        >
                          Editar
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="proj-exportar"
                          disabled={exportando === projeto.id}
                          onClick={() => void exportarProjeto(projeto)}
                        >
                          Exportar
                        </Button>
                        {!projeto.is_active && (
                          <Button
                            size="sm"
                            data-testid="proj-ativar"
                            onClick={() => {
                              setErro(null);
                              setAConfirmar(null);
                              setAtivarAlvo(projeto);
                            }}
                          >
                            Ativar
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="proj-delete"
                          onClick={() => {
                            setErro(null);
                            setAtivarAlvo(null);
                            setAConfirmar(projeto.id);
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
