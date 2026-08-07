import { Card } from "../../components/ui/card";

/**
 * Placeholder provisório (tarefa 3.1, plano F5b): a rota `/operacao/:flowId/:blockId` já
 * navega, mas os faceplates e o trend com predição chegam nas tarefas 4.1-5.3.
 */
export function OperatePage() {
  return (
    <Card className="max-w-lg p-6" data-testid="operate-page-placeholder">
      <h2 className="plaqueta text-xs text-fg-muted">Operação</h2>
      <p className="mt-2 text-sm text-fg-muted">Tela do MPC — conteúdo chega na tarefa 4.1.</p>
    </Card>
  );
}
