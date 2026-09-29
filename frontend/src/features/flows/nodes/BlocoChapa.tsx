import { Handle, Position } from "@xyflow/react";
import type { ReactNode } from "react";

import { cn } from "../../../lib/cn";
import { portaValida } from "../canalPrimitivos";
import { ROTULO_BLOCO, type TipoBloco } from "../graph";
import { formatarValorPorta, type PortValue } from "../useFlowStatus";
import { useEuHerdada, useValoresDoBloco, type PortasDoBloco } from "./contexto";

/**
 * Equipamento de painel (DESIGN.md §Shapes): chapa, plaqueta de título com o badge de
 * `exec_order`, corpo com o resumo da config e portas rotuladas em bisel de 2px. Nenhum
 * pedaço do visual default do React Flow sobrevive aqui.
 */

export interface Porta {
  id: string;
  rotulo: string;
  /** EU desta porta específica (Script/TFS declaram por porta, spec §4.1/§6.4). Ausente cai
   *  no `eu` do bloco (OPC-Read/Write: uma tag → uma EU para todas as portas). */
  eu?: string;
}

interface Props {
  tipo: TipoBloco;
  /** Rótulo do usuário; vazio cai no nome do tipo. */
  label: string;
  execOrder: number;
  selecionado: boolean;
  entradas: readonly Porta[];
  saidas: readonly Porta[];
  /** `block_id`: a chave dos valores ao vivo (§4.2) e do hot-swap (ADR-011). */
  blockId: string;
  /** EU da tag do bloco, quando o bloco tem tag (Regra do Número Tabular). */
  eu?: string | null;
  children: ReactNode;
}

/** Rótulos pt-BR de `quality` (polaridade Fieldbus BAD=0/UNCERTAIN=1/GOOD=2, ADR-043) —
 *  só no tooltip (spec §7: sem terceiro estado visual nesta entrega; o rótulo VISÍVEL é
 *  sempre "inválido" quando `!portaValida`). */
const QUALITY_ROTULO: Record<number, string> = {
  0: "inválido",
  1: "incerto",
  2: "válido",
};

/** Rótulos pt-BR dos 7 substatus do ADR-039 §Substatus; `0` (NON_SPECIFIC) nunca entra no
 *  tooltip — só os demais complementam a qualidade no hover. */
const SUBSTATUS_ROTULO: Record<number, string> = {
  0: "não especificado",
  1: "pedido de inicialização",
  2: "não convidado",
  3: "override local",
  4: "falha de sensor",
  5: "erro de configuração",
  6: "falha de dispositivo",
};

/**
 * Valor ao vivo da porta. Inválido é dessaturado **e** rotulado, nunca só descolorido
 * (Regra do Canal Redundante); o número sai em mono tabular para não dançar de largura a
 * cada varredura (Regra do Número Tabular). Quality/substatus detalhados só no `title`
 * (spec §7: tooltip mostra GOOD/UNCERTAIN/BAD e substatus quando ≠ NON_SPECIFIC; sem
 * terceiro estado visual no rótulo desta entrega).
 */
function ValorPorta({ valor, eu }: { valor: PortValue | undefined; eu?: string | null }) {
  if (valor === undefined) {
    return (
      <span data-testid="porta-valor" className="text-[10px] leading-none text-fg-muted">
        aguardando dado
      </span>
    );
  }
  const numerico = typeof valor.v === "number";
  const valida = portaValida(valor);
  const titulo = `${QUALITY_ROTULO[valor.quality] ?? "inválido"}${
    valor.substatus !== 0 ? ` · ${SUBSTATUS_ROTULO[valor.substatus]}` : ""
  }`;
  return (
    <span data-testid="porta-valor" className="flex items-baseline gap-1 leading-none" title={titulo}>
      <span
        className={cn(
          "process-value text-[11px] font-bold",
          valida ? "text-fg" : "text-fg-muted",
        )}
      >
        {formatarValorPorta(valor)}
      </span>
      {numerico && eu ? <span className="text-[9px] font-bold text-fg-muted">{eu}</span> : null}
      {!valida && <span className="text-[9px] text-fg-muted">inválido</span>}
    </span>
  );
}

function LinhaPorta({
  porta,
  lado,
  valores,
  eu,
  noId,
}: {
  porta: Porta;
  lado: "entrada" | "saida";
  valores: PortasDoBloco | null;
  eu?: string | null;
  noId: string;
}) {
  const entrada = lado === "entrada";
  const euHerdada = useEuHerdada(noId, porta.id);
  return (
    <div
      className={cn(
        "relative flex min-h-6 flex-col justify-center gap-0.5 py-0.5",
        entrada ? "items-start pl-3" : "items-end pr-3",
      )}
    >
      <Handle
        type={entrada ? "target" : "source"}
        position={entrada ? Position.Left : Position.Right}
        id={porta.id}
      />
      <span className="plaqueta text-[10px] leading-none text-fg-muted">{porta.rotulo}</span>
      {valores !== null && (
        <ValorPorta valor={valores[porta.id]} eu={porta.eu ?? euHerdada ?? eu} />
      )}
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
  blockId,
  eu,
  children,
}: Props) {
  const titulo = label.trim() || ROTULO_BLOCO[tipo];
  const valores = useValoresDoBloco(blockId);
  return (
    <div
      className={cn(
        "w-[212px] overflow-hidden rounded-md border bg-surface text-fg shadow-sm transition-shadow duration-[var(--duration-fast)]",
        selecionado ? "border-accent shadow-[var(--shadow-glow-accent)]" : "border-border hover:shadow-md",
      )}
    >
      {/* Plaqueta de título: badge de exec_order em mono tabular + nome gravado */}
      <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-2.5 py-2">
        <span
          title="Ordem de execução na varredura"
          className="process-value flex h-5 min-w-5 items-center justify-center rounded-pill bg-accent-soft px-1.5 text-[11px] leading-none text-accent-strong"
        >
          {execOrder}
        </span>
        <span className="plaqueta truncate text-[11px] leading-none text-fg">{titulo}</span>
      </div>

      <div className="px-3 py-2 text-[11px] leading-tight text-fg-muted">{children}</div>

      {(entradas.length > 0 || saidas.length > 0) && (
        <div className="flex border-t border-border py-1">
          <div className="flex-1">
            {entradas.map((porta) => (
              <LinhaPorta key={porta.id} porta={porta} lado="entrada" valores={valores} eu={eu} noId={blockId} />
            ))}
          </div>
          <div className="flex-1">
            {saidas.map((porta) => (
              <LinhaPorta key={porta.id} porta={porta} lado="saida" valores={valores} eu={eu} noId={blockId} />
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
