import { useEffect, useState } from "react";

import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";

/** Teto da janela: 7 dias em segundos (mesmo teto do preset "7d" que este componente
 *  substitui — além disso o histórico fica grande demais para a tela). */
export const JANELA_MAX_SEGUNDOS = 604800;

type Unidade = "seg" | "min";

interface Props {
  /** Janela atual, sempre em segundos. */
  segundos: number;
  /** Chamado só com valores válidos (inteiro > 0, ≤ teto), já convertidos em segundos. */
  onChange: (segundos: number) => void;
  /** Prefixo dos testids: `${prefixo}-janela-valor` / `${prefixo}-janela-unidade`. */
  prefixoTestid: string;
}

function derivarCampos(segundos: number): { valor: string; unidade: Unidade } {
  return segundos % 60 === 0
    ? { valor: String(segundos / 60), unidade: "min" }
    : { valor: String(segundos), unidade: "seg" };
}

/**
 * Janela de tempo por valor + unidade (segundos/minutos), compartilhada pelo trend de
 * engenharia e pelo trend de operação. Commit no blur, no Enter e na troca de unidade;
 * entrada não-numérica ou ≤ 0 reverte ao valor anterior — o gráfico nunca recebe janela
 * inválida.
 */
export function JanelaTempo({ segundos, onChange, prefixoTestid }: Props) {
  const [valor, setValor] = useState(() => derivarCampos(segundos).valor);
  const [unidade, setUnidade] = useState<Unidade>(() => derivarCampos(segundos).unidade);

  // Fonte externa mudou (ex.: reset de layout): o campo volta a refletir o estado.
  useEffect(() => {
    const campos = derivarCampos(segundos);
    setValor(campos.valor);
    setUnidade(campos.unidade);
  }, [segundos]);

  function commitar(novoValor: string, novaUnidade: Unidade): void {
    const numero = Number(novoValor);
    if (!Number.isFinite(numero) || numero <= 0) {
      setValor(derivarCampos(segundos).valor); // reverte ao anterior
      return;
    }
    const total = Math.min(
      Math.round(numero) * (novaUnidade === "min" ? 60 : 1),
      JANELA_MAX_SEGUNDOS,
    );
    if (total !== segundos) onChange(total);
    // Normaliza o campo (ex.: "1.9" min vira "1"; 90 min exibe "90", não "1.5 h").
    setValor(derivarCampos(total).valor);
    setUnidade(derivarCampos(total).unidade);
  }

  return (
    <span className="flex items-center gap-1.5">
      <span className="plaqueta text-xs text-fg-muted">Janela</span>
      <Input
        type="number"
        min={1}
        step={1}
        aria-label="Janela de tempo"
        data-testid={`${prefixoTestid}-janela-valor`}
        className="h-7 w-16 px-2 text-xs"
        value={valor}
        onChange={(evento) => setValor(evento.target.value)}
        onBlur={() => commitar(valor, unidade)}
        onKeyDown={(evento) => {
          if (evento.key === "Enter") commitar(valor, unidade);
        }}
      />
      <Select
        aria-label="Unidade da janela"
        data-testid={`${prefixoTestid}-janela-unidade`}
        className="h-7 w-24 px-2 text-xs"
        value={unidade}
        onChange={(evento) => {
          const novaUnidade = evento.target.value as Unidade;
          commitar(valor, novaUnidade);
        }}
      >
        <option value="min">minutos</option>
        <option value="seg">segundos</option>
      </Select>
    </span>
  );
}
