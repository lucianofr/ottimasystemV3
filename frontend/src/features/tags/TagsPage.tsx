import { useState } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError, type TagOut } from "../../lib/api";
import { TagForm } from "./TagForm";
import {
  ROTULO_DIRECAO,
  ROTULO_TIPO,
  useAllConnections,
  useDeleteTag,
  useTags,
  type Direcao,
  type FiltrosTags,
} from "./useTags";

const COLUNAS = [
  "Nome",
  "Conexão",
  "Node ID",
  "Direção",
  "Tipo",
  "EU",
  "Descrição",
] as const;

export function TagsPage() {
  const [filtros, setFiltros] = useState<FiltrosTags>({ connectionId: null, direction: null });
  const conexoes = useAllConnections();
  const tags = useTags(filtros);
  const excluir = useDeleteTag();
  const [formAberto, setFormAberto] = useState(false);
  const [emEdicao, setEmEdicao] = useState<TagOut | null>(null);
  const [aConfirmar, setAConfirmar] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const listaConexoes = conexoes.data ?? [];
  const nomePorConexao = new Map(listaConexoes.map((conexao) => [conexao.id, conexao.name]));
  const linhas = tags.data ?? [];
  const filtrando = filtros.connectionId !== null || filtros.direction !== null;

  function abrirCriacao(): void {
    setEmEdicao(null);
    setAConfirmar(null);
    setErro(null);
    setFormAberto(true);
  }

  function abrirEdicao(tag: TagOut): void {
    setEmEdicao(tag);
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

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Tags</h1>
        <Button
          data-testid="tag-new"
          onClick={abrirCriacao}
          disabled={listaConexoes.length === 0}
        >
          Nova tag
        </Button>
      </div>

      {conexoes.isSuccess && listaConexoes.length === 0 && (
        <p className="text-sm text-fg-muted">
          Nenhuma conexão cadastrada: cadastre uma conexão antes de criar tags.
        </p>
      )}

      {/* Filtros server-side: viram query params de GET /api/tags (spec F2 §9.1) */}
      <Card className="flex flex-wrap items-end gap-4 p-4">
        <div className="w-64 space-y-1.5">
          <Label htmlFor="filter-connection">Conexão</Label>
          <Select
            id="filter-connection"
            data-testid="filter-connection"
            value={filtros.connectionId === null ? "" : String(filtros.connectionId)}
            onChange={(e) =>
              setFiltros((atual) => ({
                ...atual,
                connectionId: e.target.value === "" ? null : Number(e.target.value),
              }))
            }
          >
            <option value="">Todas</option>
            {listaConexoes.map((conexao) => (
              <option key={conexao.id} value={String(conexao.id)}>
                {conexao.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-48 space-y-1.5">
          <Label htmlFor="filter-direction">Direção</Label>
          <Select
            id="filter-direction"
            data-testid="filter-direction"
            value={filtros.direction ?? ""}
            onChange={(e) =>
              setFiltros((atual) => ({
                ...atual,
                direction: e.target.value === "" ? null : (e.target.value as Direcao),
              }))
            }
          >
            <option value="">Todas</option>
            <option value="r">{ROTULO_DIRECAO.r}</option>
            <option value="w">{ROTULO_DIRECAO.w}</option>
          </Select>
        </div>
      </Card>

      {formAberto && (
        <TagForm
          key={emEdicao?.id ?? "nova"}
          tag={emEdicao}
          conexoes={listaConexoes}
          onClose={() => setFormAberto(false)}
        />
      )}

      {erro && (
        <p role="alert" data-testid="tag-error" className="text-sm text-alarm">
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
              <th className="px-3 py-2">
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {tags.isPending && (
              <tr>
                <td colSpan={COLUNAS.length + 1} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {tags.isError && (
              <tr>
                <td colSpan={COLUNAS.length + 1} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar tags
                </td>
              </tr>
            )}
            {tags.isSuccess && linhas.length === 0 && (
              <tr>
                <td
                  colSpan={COLUNAS.length + 1}
                  data-testid="tag-empty"
                  className="px-3 py-4 text-fg-muted"
                >
                  {filtrando ? "Nenhuma tag para este filtro" : "Nenhuma tag cadastrada"}
                </td>
              </tr>
            )}
            {linhas.map((tag) => (
              <tr key={tag.id} data-testid="tag-row" className="border-b border-hairline">
                <td className="px-3 py-2">{tag.name}</td>
                <td className="px-3 py-2">
                  {nomePorConexao.get(tag.connection_id) ?? (
                    <span className="text-fg-muted">—</span>
                  )}
                </td>
                <td className="process-value px-3 py-2">{tag.node_id}</td>
                <td className="px-3 py-2">{ROTULO_DIRECAO[tag.direction]}</td>
                <td className="px-3 py-2">{ROTULO_TIPO[tag.data_type]}</td>
                <td className="px-3 py-2 text-fg-muted">
                  {tag.eu || <span className="text-fg-muted">—</span>}
                </td>
                <td className="px-3 py-2">
                  {tag.description || <span className="text-fg-muted">—</span>}
                </td>
                <td className="px-3 py-2">
                  {aConfirmar === tag.id ? (
                    <div className="flex items-center justify-end gap-2">
                      <span className="text-xs text-fg-muted">Excluir esta tag?</span>
                      <Button
                        variant="destructive"
                        size="sm"
                        data-testid="tag-delete-confirm"
                        disabled={excluir.isPending}
                        onClick={() => void confirmarExclusao(tag.id)}
                      >
                        Confirmar
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="tag-delete-cancel"
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
                        data-testid="tag-edit"
                        onClick={() => abrirEdicao(tag)}
                      >
                        Editar
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="tag-delete"
                        onClick={() => {
                          setErro(null);
                          setAConfirmar(tag.id);
                        }}
                      >
                        Excluir
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}
