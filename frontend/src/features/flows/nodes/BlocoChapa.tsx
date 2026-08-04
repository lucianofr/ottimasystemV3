import { Handle, Position } from "@xyflow/react";
import type { ReactNode } from "react";

import { cn } from "../../../lib/cn";
import { ROTULO_BLOCO, type TipoBloco } from "../graph";

/**
 * Equipamento de painel (DESIGN.md §Shapes): chapa, plaqueta de título com o badge de
 * `exec_order`, corpo com o resumo da config e portas rotuladas em bisel de 2px. Nenhum
 * pedaço do visual default do React Flow sobrevive aqui.
 */

export interface Porta {
  id: string;
  rotulo: string;
}

interface Props {
  tipo: TipoBloco;
  /** Rótulo do usuário; vazio cai no nome do tipo. */
  label: string;
  execOrder: number;
  selecionado: boolean;
  entradas: readonly Porta[];
  saidas: readonly Porta[];
  children: ReactNode;
}

function LinhaPorta({ porta, lado }: { porta: Porta; lado: "entrada" | "saida" }) {
  const entrada = lado === "entrada";
  return (
    <div
      className={cn(
        "relative flex h-6 items-center",
        entrada ? "justify-start pl-3" : "justify-end pr-3",
      )}
    >
      <Handle
        type={entrada ? "target" : "source"}
        position={entrada ? Position.Left : Position.Right}
        id={porta.id}
      />
      <span className="plaqueta text-[10px] leading-none text-fg-muted">{porta.rotulo}</span>
    </div>
  );
}

export function BlocoChapa({
  tipo,
  label,
  execOrder,
  selecionado,
  entradas,
  saidas,
  children,
}: Props) {
  const titulo = label.trim() || ROTULO_BLOCO[tipo];
  return (
    <div
      className={cn(
        "w-[212px] rounded-panel border bg-panel text-fg",
        selecionado ? "border-accent" : "border-hairline",
      )}
    >
      {/* Plaqueta de título: badge de exec_order em mono tabular + nome gravado */}
      <div className="flex items-center gap-2 border-b border-hairline bg-well px-2 py-1.5">
        <span
          title="Ordem de execução na varredura"
          className="process-value flex h-5 min-w-5 items-center justify-center rounded-[2px] border border-hairline bg-field px-1 text-[11px] leading-none text-fg"
        >
          {execOrder}
        </span>
        <span className="plaqueta truncate text-[11px] leading-none text-fg">{titulo}</span>
      </div>

      <div className="px-3 py-2 text-[11px] leading-tight text-fg-muted">{children}</div>

      {(entradas.length > 0 || saidas.length > 0) && (
        <div className="flex border-t border-hairline py-1">
          <div className="flex-1">
            {entradas.map((porta) => (
              <LinhaPorta key={porta.id} porta={porta} lado="entrada" />
            ))}
          </div>
          <div className="flex-1">
            {saidas.map((porta) => (
              <LinhaPorta key={porta.id} porta={porta} lado="saida" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Rodapé de valor: nome da tag, contagem de portas, matriz — sempre com rótulo textual. */
export function LinhaResumo({ rotulo, valor }: { rotulo: string; valor: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="plaqueta text-[10px] text-fg-muted">{rotulo}</span>
      <span className="truncate text-right text-[11px] text-fg">{valor}</span>
    </div>
  );
}
