import { useState } from "react";
import { Link } from "react-router";

import { useAssinaturaOpcValues, useCanalAoVivo, type LeituraTag } from "../../app/CanalAoVivo";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ApiError, type TagOut } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useCanMutate } from "../auth/useAuth";
import { useConnections } from "../connections/useConnections";
import { useActiveProject } from "../projects/useProjects";
import { TagCalculadaForm } from "./TagCalculadaForm";
import { TagForm } from "./TagForm";
import { eCalculada, tagsElegiveis } from "./tagCalculada";
import { celulaOnline, type CelulaOnline } from "./tagsOnline";
import { formatarPeriodo, useCalculatedTag, useCalculatedTags, useDeleteCalculatedTag } from "./useCalculatedTags";
import {
  ROTULO_DIRECAO,
  ROTULO_TIPO,
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
  "Período",
  "EU",
  "Valor",
  "Quality",
  "Descrição",
] as const;

/** Cor da lâmpada de quality. Boa fica NEUTRA de propósito (Regra da Cor Anormal: superfície
 *  em operação normal não tem cor) — a forma é que distingue boa de sem-dado. */
const COR_QUALITY: Record<"success" | "warn" | "alarm", string> = {
  success: "text-fg-muted",
  warn: "text-warn-fg",
  alarm: "text-alarm",
};

/** Lâmpada de quality: forma + cor + rótulo textual (Regra do Canal Redundante, DESIGN.md
 *  §Colors) — mesma convenção de `LampadaSeveridade` (`EventsPage.tsx`), com vocabulário de
 *  forma próprio porque o domínio (quality do OPC-UA, não severidade de evento) é outro:
 *  círculo = boa, triângulo = incerta, losango = ruim. Sem dado não acende lâmpada. */
function LampadaQuality({ celula }: { celula: CelulaOnline }) {
  if (celula.tone === "neutral") return <span className="text-fg-muted">{celula.quality}</span>;
  return (
    <span className={cn("inline-flex items-center gap-1.5", COR_QUALITY[celula.tone])}>
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {celula.tone === "success" && <circle cx="5" cy="5" r="4" />}
        {celula.tone === "warn" && <path d="M5 0 10 9H0L5 0Z" />}
        {celula.tone === "alarm" && <path d="M5 0 10 5 5 10 0 5Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{celula.quality}</span>
    </span>
  );
}

/** Valor online + quality de uma linha (RF-204). Subcomponente para `celulaOnline` rodar uma
 *  vez por linha e ainda entregar duas células. A Regra do Número Tabular pede mono tabular
 *  com a EU ao lado: `process-value` fica no span do NÚMERO, não no `<td>`, senão a EU herda
 *  o mono por cascata (mesmo recorte de `BlocoChapa.tsx` e `FlowsPage.tsx`). */
function CelulasOnline({
  tag,
  leitura,
  aoVivo,
}: {
  tag: TagOut;
  leitura: LeituraTag | undefined;
  aoVivo: boolean;
}) {
  const celula = celulaOnline(leitura, aoVivo);
  return (
    <>
      <td className="px-3 py-2 text-right" data-testid="tag-valor">
        {celula.valor === null ? (
          <span className="text-fg-muted">—</span>
        ) : (
          <>
            <span className="process-value">{celula.valor}</span>
            {/* Espaço de TEXTO, não só margem: a célula é copiável e vai a leitor de tela. */}
            {tag.eu !== "" && <> <span className="text-xs text-fg-muted">{tag.eu}</span></>}
          </>
        )}
      </td>
      <td className="px-3 py-2" data-testid="tag-quality">
        <LampadaQuality celula={celula} />
      </td>
    </>
  );
}

export function TagsPage() {
  const [filtros, setFiltros] = useState<FiltrosTags>({ connectionId: null, direction: null });
  const projeto = useActiveProject();
  const projetoAtivoId = projeto.data?.id ?? null;
  const conexoes = useConnections(projetoAtivoId);
  const tags = useTags(filtros);
  const calcTags = useCalculatedTags(projetoAtivoId);
  const excluir = useDeleteTag();
  const excluirCalc = useDeleteCalculatedTag();
  const [formAberto, setFormAberto] = useState(false);
  const [emEdicao, setEmEdicao] = useState<TagOut | null>(null);
  const [formCalcAberto, setFormCalcAberto] = useState(false);
  const [emEdicaoCalcId, setEmEdicaoCalcId] = useState<number | null>(null);
  const calcEmEdicao = useCalculatedTag(emEdicaoCalcId);
  const [aConfirmar, setAConfirmar] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const listaConexoes = conexoes.data ?? [];
  const nomePorConexao = new Map(listaConexoes.map((conexao) => [conexao.id, conexao.name]));
  const idsConexoesDoProjeto = new Set(nomePorConexao.keys());
  const periodoPorId = new Map((calcTags.data ?? []).map((c) => [c.id, c.period_seconds]));
  // Escopo por projeto ativo em memória: `GET /api/tags` não aceita `project_id` (API da F1) e
  // devolve toda tag, inclusive calculada de outro projeto — o discriminador (`eCalculada`,
  // ADR-033 D1) decide a regra: OPC entra pela conexão do projeto, calculada entra pelo próprio
  // `project_id` (ela não tem conexão nenhuma).
  const linhas = (tags.data ?? []).filter((tag) => {
    if (eCalculada(tag)) return tag.project_id === projetoAtivoId;
    return tag.connection_id !== null && idsConexoesDoProjeto.has(tag.connection_id);
  });
  const entradasElegiveis = tagsElegiveis(
    tags.data ?? [],
    projetoAtivoId,
    idsConexoesDoProjeto,
    emEdicaoCalcId,
  );
  const filtrando = filtros.connectionId !== null || filtros.direction !== null;
  const podeMutar = useCanMutate();
  const totalColunas = COLUNAS.length + (podeMutar ? 1 : 0);
  // Assinatura DINÂMICA: o conjunto de linhas muda com os filtros e com o projeto ativo, sem
  // remontar a página — `useAssinatura` congelaria o interesse do primeiro render. Toda tag
  // entra, inclusive a de escrita e a calculada: ambas publicam no mesmo `opc_values` do WS
  // (tag calculada via `calc.values`, sem mudança de contrato no `/ws`, ADR-033 D2).
  useAssinaturaOpcValues(linhas.map((tag) => tag.id));
  const { estado, tagValues } = useCanalAoVivo();
  // Socket fora do ar ⇒ `tagValues` congela no último lote; a célula vira travessão em vez de
  // exibir número velho como se fosse a leitura de agora (ver `celulaOnline`).
  const aoVivo = estado === "aberto";

  if (projeto.data === null && projeto.isSuccess) {
    return (
      <section className="space-y-4">
        <h1 className="plaqueta text-sm">Tags</h1>
        <p data-testid="tag-no-project" className="text-sm text-fg-muted">
          Nenhum projeto ativo:{" "}
          <Link to="/engenharia/projetos" className="text-accent hover:underline">
            ative um projeto
          </Link>{" "}
          para gerenciar tags.
        </p>
      </section>
    );
  }

  function fecharFormularios(): void {
    setFormAberto(false);
    setFormCalcAberto(false);
    setEmEdicao(null);
    setEmEdicaoCalcId(null);
    setAConfirmar(null);
    setErro(null);
  }

  function abrirCriacao(): void {
    fecharFormularios();
    setFormAberto(true);
  }

  function abrirEdicao(tag: TagOut): void {
    fecharFormularios();
    setEmEdicao(tag);
    setFormAberto(true);
  }

  function abrirCriacaoCalc(): void {
    fecharFormularios();
    setFormCalcAberto(true);
  }

  function abrirEdicaoCalc(tag: TagOut): void {
    fecharFormularios();
    setEmEdicaoCalcId(tag.id);
    setFormCalcAberto(true);
  }

  async function confirmarExclusao(tag: TagOut): Promise<void> {
    setErro(null);
    try {
      if (eCalculada(tag)) {
        await excluirCalc.mutateAsync(tag.id);
      } else {
        await excluir.mutateAsync(tag.id);
      }
      setAConfirmar(null);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="plaqueta text-sm">Tags</h1>
        {podeMutar && (
          <div className="flex gap-2">
            <Button
              data-testid="tag-new"
              onClick={abrirCriacao}
              disabled={listaConexoes.length === 0}
            >
              Nova tag
            </Button>
            <Button
              variant="outline"
              data-testid="calc-new"
              onClick={abrirCriacaoCalc}
              disabled={projetoAtivoId === null}
            >
              Nova tag calculada
            </Button>
          </div>
        )}
      </div>

      {podeMutar && conexoes.isSuccess && listaConexoes.length === 0 && (
        <p className="text-sm text-fg-muted">
          Nenhuma conexão cadastrada: cadastre uma conexão antes de criar tags OPC. Tag calculada
          não depende de conexão.
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

      {podeMutar && formAberto && (
        <TagForm
          key={emEdicao?.id ?? "nova"}
          tag={emEdicao}
          conexoes={listaConexoes}
          onClose={() => setFormAberto(false)}
        />
      )}

      {podeMutar &&
        formCalcAberto &&
        projetoAtivoId !== null &&
        (emEdicaoCalcId !== null && calcEmEdicao.isPending ? (
          <Card className="p-6 text-sm text-fg-muted" data-testid="calc-form-loading">
            Carregando tag calculada…
          </Card>
        ) : emEdicaoCalcId !== null && calcEmEdicao.isError ? (
          <Card className="p-6 text-sm text-alarm" role="alert" data-testid="calc-form-load-error">
            Falha ao carregar tag calculada
          </Card>
        ) : (
          <TagCalculadaForm
            key={emEdicaoCalcId ?? "nova"}
            tag={emEdicaoCalcId === null ? null : (calcEmEdicao.data ?? null)}
            tagsDisponiveis={entradasElegiveis}
            projectId={projetoAtivoId}
            onClose={() => setFormCalcAberto(false)}
          />
        ))}

      {erro && (
        <p role="alert" data-testid="tag-error" className="text-sm text-alarm">
          {erro}
        </p>
      )}

      {/* Tabela em chapa: bg-surface, hairline, cabeçalho em plaqueta (DESIGN.md §Elevation) */}
      <Card className="overflow-hidden">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2">
              {COLUNAS.map((coluna) => (
                <th key={coluna} className="plaqueta px-4 py-3 text-left text-xs text-fg-muted">
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
            {tags.isPending && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {tags.isError && (
              <tr>
                <td colSpan={totalColunas} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar tags
                </td>
              </tr>
            )}
            {tags.isSuccess && linhas.length === 0 && (
              <tr>
                <td
                  colSpan={totalColunas}
                  data-testid="tag-empty"
                  className="px-3 py-4 text-fg-muted"
                >
                  {filtrando ? "Nenhuma tag para este filtro" : "Nenhuma tag cadastrada"}
                </td>
              </tr>
            )}
            {linhas.map((tag) => {
              const periodo = periodoPorId.get(tag.id);
              return (
                <tr key={tag.id} data-testid="tag-row" className="border-b border-border transition-colors duration-[var(--duration-fast)] hover:bg-surface-2">
                  <td className="px-3 py-2">{tag.name}</td>
                  <td className="px-3 py-2">
                    {eCalculada(tag) ? (
                      <Badge tone="accent">Calculada</Badge>
                    ) : (
                      (tag.connection_id !== null
                        ? nomePorConexao.get(tag.connection_id)
                        : undefined) ?? <span className="text-fg-muted">—</span>
                    )}
                  </td>
                  <td className="process-value px-3 py-2">
                    {tag.node_id ?? <span className="text-fg-muted">—</span>}
                  </td>
                  <td className="px-3 py-2">{ROTULO_DIRECAO[tag.direction]}</td>
                  <td className="px-3 py-2">{ROTULO_TIPO[tag.data_type]}</td>
                  <td className="process-value px-3 py-2">
                    {periodo !== undefined ? (
                      formatarPeriodo(periodo)
                    ) : (
                      <span className="text-fg-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-fg-muted">
                    {tag.eu || <span className="text-fg-muted">—</span>}
                  </td>
                  <CelulasOnline tag={tag} leitura={tagValues.get(tag.id)} aoVivo={aoVivo} />
                  <td className="px-3 py-2">
                    {tag.description || <span className="text-fg-muted">—</span>}
                  </td>
                  {podeMutar && (
                    <td className="px-3 py-2">
                      {aConfirmar === tag.id ? (
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-xs text-fg-muted">Excluir esta tag?</span>
                          <Button
                            variant="destructive"
                            size="sm"
                            data-testid="tag-delete-confirm"
                            disabled={excluir.isPending || excluirCalc.isPending}
                            onClick={() => void confirmarExclusao(tag)}
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
                            onClick={() =>
                              eCalculada(tag) ? abrirEdicaoCalc(tag) : abrirEdicao(tag)
                            }
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
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </section>
  );
}
