import { Input } from "../../components/ui/input";
import type { EscalaVar } from "./escalas";

/**
 * Controle de escala Y de UMA variável, para viver na linha da legenda dos dois trends.
 *
 * Compacto de propósito: em operação a legenda tem até 8 linhas e o trend é o que precisa do
 * espaço, não o editor. Com "Auto" marcado os extremos ficam desabilitados mas VISÍVEIS — o
 * operador vê a faixa que voltará a valer ao desmarcar, em vez de digitar tudo de novo.
 */

export interface EditorEscalaProps {
  readonly escala: EscalaVar;
  /** Prefixo dos `data-testid`: `operate` na tela de operação, `trend` na de engenharia. */
  readonly prefixoTestid: string;
  readonly aoMudar: (escala: EscalaVar) => void;
}

/** Campo vazio é "sem limite digitado", não zero — zero é um extremo legítimo de faixa. */
function extremo(texto: string): number | null {
  if (texto.trim() === "") return null;
  const valor = Number(texto);
  return Number.isFinite(valor) ? valor : null;
}

function textoDoExtremo(valor: number | null): string {
  return valor === null ? "" : String(valor);
}

export function EditorEscala({ escala, prefixoTestid, aoMudar }: EditorEscalaProps) {
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <Input
        type="number"
        aria-label="Mínimo da escala"
        data-testid={`${prefixoTestid}-escala-min`}
        className="h-7 w-20 px-2 text-xs"
        disabled={escala.auto}
        value={textoDoExtremo(escala.min)}
        onChange={(evento) => {
          aoMudar({ ...escala, min: extremo(evento.target.value) });
        }}
      />
      <Input
        type="number"
        aria-label="Máximo da escala"
        data-testid={`${prefixoTestid}-escala-max`}
        className="h-7 w-20 px-2 text-xs"
        disabled={escala.auto}
        value={textoDoExtremo(escala.max)}
        onChange={(evento) => {
          aoMudar({ ...escala, max: extremo(evento.target.value) });
        }}
      />
      <label className="flex cursor-pointer items-center gap-1">
        <input
          type="checkbox"
          className="accent-accent"
          data-testid={`${prefixoTestid}-escala-auto`}
          checked={escala.auto}
          onChange={(evento) => {
            aoMudar({ ...escala, auto: evento.target.checked });
          }}
        />
        <span className="plaqueta text-xs text-fg-muted">Auto</span>
      </label>
    </span>
  );
}
