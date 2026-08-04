import { Card } from "../../components/ui/card";

/** Tela de tags. A tabela e o formulário entram na tarefa 6.3. */
export function TagsPage() {
  return (
    <section>
      <h1 className="plaqueta text-sm">Tags</h1>
      <Card className="mt-4 max-w-lg p-6">
        <p className="text-sm text-fg-muted">Nenhuma tag cadastrada</p>
      </Card>
    </section>
  );
}
