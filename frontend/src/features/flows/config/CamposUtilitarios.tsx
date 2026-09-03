import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { type NoIntegrator, type NoScaler } from "../graph";
import { BASES_TEMPO } from "../registro";
import { Campo } from "./CamposComuns";

/**
 * Formulários dos blocos utilitários Scaler e Integrator.
 *
 * Mesma disciplina dos filtros (`CamposFiltros.tsx`): campos não-controlados lidos no
 * envio por `numeroDoCampo` (vírgula decimal pt-BR); o único controle discreto é a base
 * de tempo do Integrator, que não remonta o formulário — é um `<select>` comum.
 */

const ROTULO_BASE: Record<(typeof BASES_TEMPO)[number], string> = {
  s: "por segundo",
  min: "por minuto",
  h: "por hora",
};

export function CamposScaler({ dados }: { dados: NoScaler["data"] }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Campo
          id="in_min"
          rotulo="Entrada — mínimo"
          valor={dados.in_min}
          ajuda="Valor da entrada que mapeia para o mínimo da saída."
        />
        <Campo
          id="in_max"
          rotulo="Entrada — máximo"
          valor={dados.in_max}
          ajuda="Precisa ser maior que o mínimo da entrada (é o divisor da proporcionalidade)."
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Campo
          id="out_min"
          rotulo="Saída — mínimo"
          valor={dados.out_min}
          ajuda="Valor da saída quando a entrada está no mínimo."
        />
        <Campo
          id="out_max"
          rotulo="Saída — máximo"
          valor={dados.out_max}
          ajuda="Pode ser menor que o mínimo da saída (ação reversa, ex.: 4-20 mA → 100-0 %). Fora da faixa de entrada o bloco extrapola, não trava."
        />
      </div>
    </div>
  );
}

export function CamposIntegrator({ dados }: { dados: NoIntegrator["data"] }) {
  return (
    <div className="space-y-1">
      <Label htmlFor="time_base">Base de tempo da entrada</Label>
      <Select id="time_base" name="time_base" data-testid="config-time-base" defaultValue={dados.time_base}>
        {BASES_TEMPO.map((base) => (
          <option key={base} value={base}>
            {ROTULO_BASE[base]}
          </option>
        ))}
      </Select>
      <p className="text-[10px] leading-tight text-fg-muted">
        Unidade de tempo em que a entrada está expressa (ex.: vazão em kg/min ⇒ por minuto).
        A porta `reset` (opcional) zera o total quando recebe valor diferente de zero.
      </p>
    </div>
  );
}
