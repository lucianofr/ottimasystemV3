import { Card } from "../../components/ui/card";
import { cn } from "../../lib/cn";
import { ROTULO_BLOCO, TIPOS_BLOCO, type TipoBloco } from "./graph";

/** Tipo MIME do arraste da paleta; evita reagir a qualquer outro drop no canvas. */
export const MIME_BLOCO = "application/x-ottima-bloco";

const DESCRICAO: Record<TipoBloco, string> = {
  opc_read: "Lê o valor corrente de uma tag do projeto",
  opc_write: "Escreve o valor da entrada em uma tag do projeto",
  script: "Código Python com IN1..INn e OUT1..OUTn",
  tfs: "Matriz 2x2 de funções de transferência (SOPDT/IOPDT)",
  mpc: "Controle preditivo multivariável — portas dinâmicas conforme o config",
};

interface Props {
  /** Clique adiciona no centro do canvas; o arraste posiciona onde soltar. */
  onAdicionar: (tipo: TipoBloco) => void;
}

function ItemPaleta({ tipo, onAdicionar }: { tipo: TipoBloco; onAdicionar: Props["onAdicionar"] }) {
  return (
    <button
      type="button"
      draggable
      data-testid={`paleta-${tipo}`}
      onDragStart={(evento) => {
        evento.dataTransfer.setData(MIME_BLOCO, tipo);
        evento.dataTransfer.effectAllowed = "copy";
      }}
      onClick={() => {
        onAdicionar(tipo);
      }}
      className={cn(
        "w-full cursor-grab rounded-sm border border-border bg-well px-2 py-2 text-left",
        "hover:border-accent focus-visible:outline-2 focus-visible:outline-accent active:cursor-grabbing",
      )}
    >
      <span className="plaqueta block text-[11px] text-fg">{ROTULO_BLOCO[tipo]}</span>
      <span className="mt-0.5 block text-[10px] leading-tight text-fg-muted">
        {DESCRICAO[tipo]}
      </span>
    </button>
  );
}

/** Paleta de 5 blocos (RF-301): o MPC entra em operação na F4 (decisão A-1) igual aos
 *  demais — arrastável, sem badge de fase pendente (spec F4 §7.1). */
export function FlowPalette({ onAdicionar }: Props) {
  return (
    <Card className="w-56 shrink-0 space-y-2 p-3">
      <h2 className="plaqueta text-[11px] text-fg-muted">Paleta</h2>
      <p className="text-[10px] leading-tight text-fg-muted">
        Arraste para o canvas ou clique para inserir no centro.
      </p>
      <div className="space-y-2">
        {TIPOS_BLOCO.map((tipo) => (
          <ItemPaleta key={tipo} tipo={tipo} onAdicionar={onAdicionar} />
        ))}
      </div>
    </Card>
  );
}
