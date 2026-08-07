import { Card } from "../../components/ui/card";

/**
 * Placeholder provisório (tarefa 3.1, plano F5b): a rota `/operacao` já navega, mas a
 * lista de MPCs (`GET /api/operate/mpcs`) e o redirect direto com 1 único MPC chegam na
 * tarefa 4.1 (spec F5 §7.4-1).
 */
export function OperateSelectorPage() {
  return (
    <Card className="max-w-lg p-6" data-testid="operate-selector-placeholder">
      <h2 className="plaqueta text-xs text-fg-muted">Operação</h2>
      <p className="mt-2 text-sm text-fg-muted">Seletor de MPC — conteúdo chega na tarefa 4.1.</p>
    </Card>
  );
}
