import { Card } from "../../components/ui/card";

/** Tela de conexões OPC-UA. A tabela e o formulário entram na tarefa 6.2. */
export function ConnectionsPage() {
  return (
    <section>
      <h1 className="plaqueta text-sm">Conexões</h1>
      <Card className="mt-4 max-w-lg p-6">
        <p className="text-sm text-fg-muted">Nenhuma conexão cadastrada</p>
      </Card>
    </section>
  );
}
