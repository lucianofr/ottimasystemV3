import { Card } from "../../components/ui/card";

/**
 * Placeholder provisório (tarefa 3.1, plano F5b): a rota `/eventos` já navega, mas a
 * tabela filtrável (severidade/origem/período) chega na tarefa 3.3 (spec F5 §7.5).
 */
export function EventsPage() {
  return (
    <Card className="max-w-lg p-6" data-testid="eventos-placeholder">
      <h2 className="plaqueta text-xs text-fg-muted">Eventos</h2>
      <p className="mt-2 text-sm text-fg-muted">Tabela de eventos — conteúdo chega na tarefa 3.3.</p>
    </Card>
  );
}
