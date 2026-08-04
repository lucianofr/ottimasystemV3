/** Faixa anunciadora persistente (DESIGN.md §Layout).
 * F1: sempre colapsada — condições reais chegam pelo canal `events`/WS na F5 (ADR-020). */
export function AnnunciatorBar() {
  return (
    <div
      data-testid="annunciator"
      className="flex h-7 items-center border-b border-hairline bg-panel px-4"
    >
      <span className="plaqueta text-xs text-fg-muted">Sem alarmes ativos</span>
    </div>
  );
}
