import { useQuery } from "@tanstack/react-query";

import { Card } from "../components/ui/card";
import { api, type ProjectOut } from "../lib/api";

/** Valida login -> token -> cliente tipado -> dado real; não é tela CRUD (spec §8.4). */
export function HomePage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<ProjectOut[]>("/api/projects"),
  });
  const ativo = data?.find((p) => p.is_active) ?? null;
  return (
    <Card className="max-w-lg p-6">
      <h2 className="plaqueta text-xs text-fg-muted">Projeto ativo</h2>
      {isPending && <p className="mt-2 text-sm text-fg-muted">Carregando…</p>}
      {isError && (
        <p role="alert" className="mt-2 text-sm text-alarm">
          Falha ao consultar projetos
        </p>
      )}
      {!isPending && !isError && (
        <p data-testid="active-project" className="mt-2 text-lg">
          {ativo ? ativo.name : "Nenhum projeto ativo"}
        </p>
      )}
    </Card>
  );
}
