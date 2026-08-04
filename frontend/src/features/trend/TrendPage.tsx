import { Card } from "../../components/ui/card";

/** Tela de tendência. O gráfico uPlot com as penas entra na tarefa 6.4. */
export function TrendPage() {
  return (
    <section>
      <h1 className="plaqueta text-sm">Trend</h1>
      <Card className="mt-4 max-w-lg p-6">
        <p className="text-sm text-fg-muted">Selecione tags para exibir</p>
      </Card>
    </section>
  );
}
