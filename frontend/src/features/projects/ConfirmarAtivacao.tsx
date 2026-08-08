import { useState } from "react";

import { Button } from "../../components/ui/button";
import { ApiError, type ProjectOut } from "../../lib/api";
import { useFlows } from "../flows/useFlows";
import { useActivateProject, useActiveProject } from "./useProjects";

/**
 * Texto do botão de confirmação (spec §6.1-4, UX-07): o verbo carrega a contagem de flows
 * que serão parados — nunca um "OK" genérico. Zero flows degrada para só "Ativar" (sem
 * contagem); um flow é singular; dois ou mais são plural com o número. Único ponto testável
 * da tarefa 2.2 — testado por igualdade exata das três formas em `ConfirmarAtivacao.check.ts`.
 */
export function textoBotaoAtivar(flowCount: number): string {
  if (flowCount === 0) return "Ativar";
  if (flowCount === 1) return "Ativar e parar 1 flow";
  return `Ativar e parar ${String(flowCount)} flows`;
}

interface Props {
  /** Projeto alvo da ativação (linha clicada) — o nome já está visível na própria linha. */
  alvo: ProjectOut;
  onCancelar: () => void;
}

/**
 * Confirmação inline da ação de maior consequência da tela (spec §6.1-4): ativar encerra a
 * execução de todos os flows do projeto ATUAL (não o alvo clicado) — efeito físico numa
 * planta. Mesmo padrão de `proj-delete-confirm`/`proj-delete-cancel` já usado em
 * `ProjectsPage.tsx` — sem `<dialog>`, sem componente de modal novo (regra global 2, FE-08).
 *
 * Não usa o pendente-até-confirmar da operação (F5 §7.4-4): aquele padrão é para comando de
 * malha com estado publicado pelo runtime; aqui a confirmação é do banco e é síncrona — o
 * sucesso da mutação já é o desfecho, sem eco a esperar.
 *
 * A contagem de flows vem de `useFlows(projetoAtualId)` — o mesmo hook e a mesma `queryKey`
 * já usados por `FlowsPage`/`HomePage`/`EventsPage`/`CanalAoVivo`; nenhum endpoint novo.
 */
export function ConfirmarAtivacao({ alvo, onCancelar }: Props) {
  const [erro, setErro] = useState<string | null>(null);
  const atual = useActiveProject();
  const projetoAtualId = atual.data?.id ?? null;
  const flows = useFlows(projetoAtualId);
  const ativar = useActivateProject();

  const contandoFlows = projetoAtualId !== null && flows.isPending;
  const contagem = flows.data?.length ?? 0;

  async function confirmar(): Promise<void> {
    setErro(null);
    try {
      await ativar.mutateAsync(alvo.id);
      // Sucesso: `useActivateProject` já invalidou projects+connections+tags+flows+
      // operate.mpcs (F6R-11) — as telas refletem o projeto novo sem reload. Só fecha
      // a confirmação; nenhum efeito extra a coordenar aqui.
      onCancelar();
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    }
  }

  return (
    <div data-testid="proj-ativar-dialog" className="flex flex-col items-end gap-1.5">
      {erro && (
        <p role="alert" data-testid="proj-ativar-error" className="text-xs text-alarm">
          {erro}
        </p>
      )}
      {flows.isError && (
        <p role="alert" data-testid="proj-ativar-contagem-error" className="text-xs text-alarm">
          Falha ao contar os flows do projeto atual
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span data-testid="proj-ativar-aviso" className="text-xs text-fg-muted">
          {atual.data
            ? `Isso vai parar os flows do projeto atual, "${atual.data.name}".`
            : "Nenhum projeto está ativo no momento."}
        </span>
        <Button
          size="sm"
          data-testid="proj-ativar-confirm"
          disabled={ativar.isPending || contandoFlows || flows.isError}
          onClick={() => void confirmar()}
        >
          {textoBotaoAtivar(contagem)}
        </Button>
        <Button variant="outline" size="sm" data-testid="proj-ativar-cancel" onClick={onCancelar}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}
