import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { ApiError, type ProjectOut } from "../../lib/api";
import {
  useCreateProject,
  useUpdateProject,
  type ProjectCreate,
  type ProjectUpdate,
} from "./useProjects";

interface Valores {
  name: string;
  description: string;
}

function valoresIniciais(projeto: ProjectOut | null): Valores {
  return { name: projeto?.name ?? "", description: projeto?.description ?? "" };
}

interface Props {
  /** `null` = criar; caso contrário, edita o projeto. */
  projeto: ProjectOut | null;
  onClose: () => void;
}

export function ProjectForm({ projeto, onClose }: Props) {
  const [v, setV] = useState<Valores>(() => valoresIniciais(projeto));
  const [erro, setErro] = useState<string | null>(null);
  const criar = useCreateProject();
  const atualizar = useUpdateProject();
  const editando = projeto !== null;
  const enviando = criar.isPending || atualizar.isPending;

  function mudar<K extends keyof Valores>(campo: K, valor: Valores[K]): void {
    setV((atual) => ({ ...atual, [campo]: valor }));
  }

  async function onSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    if (!v.name.trim()) {
      setErro("Nome é obrigatório");
      return;
    }
    setErro(null);
    try {
      if (editando) {
        const corpo: ProjectUpdate = { name: v.name.trim(), description: v.description };
        await atualizar.mutateAsync({ id: projeto.id, body: corpo });
      } else {
        const corpo: ProjectCreate = { name: v.name.trim(), description: v.description };
        await criar.mutateAsync(corpo);
      }
      onClose();
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    }
  }

  return (
    <Card className="p-6">
      <h2 className="plaqueta text-xs text-fg-muted">
        {editando ? "Editar projeto" : "Novo projeto"}
      </h2>
      <form
        data-testid="proj-form"
        onSubmit={(e) => void onSubmit(e)}
        className="mt-4 space-y-6"
        noValidate
      >
        <div className="space-y-1.5">
          <Label htmlFor="proj-name">Nome</Label>
          <Input
            id="proj-name"
            data-testid="proj-name"
            value={v.name}
            onChange={(e) => mudar("name", e.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="proj-description">Descrição</Label>
          <textarea
            id="proj-description"
            data-testid="proj-description"
            rows={2}
            value={v.description}
            onChange={(e) => mudar("description", e.target.value)}
            className="w-full rounded-panel border border-hairline bg-well px-3 py-2 text-sm text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-accent"
          />
        </div>

        {erro && (
          <p role="alert" data-testid="proj-form-error" className="text-sm text-alarm">
            {erro}
          </p>
        )}

        <div className="flex gap-3">
          <Button type="submit" data-testid="proj-submit" disabled={enviando}>
            {enviando ? "Salvando…" : "Salvar"}
          </Button>
          <Button type="button" variant="outline" data-testid="proj-cancel" onClick={onClose}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}
