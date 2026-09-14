import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { type NoBusPublish, type NoBusSubscribe, type NoConstant, type NoIntegrator, type NoScaler } from "../graph";
import { BASES_TEMPO } from "../registro";
import { Campo } from "./CamposComuns";

/**
 * Formulários dos blocos utilitários Scaler, Integrator e Constante.
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
          ajuda="Pode ser menor que o mínimo da saída (ação reversa, ex.: 4-20 mA → 100-0 %). Fora da faixa de entrada o bloco extrapola — conversão de unidade não satura; limitar é função de outro bloco."
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

export function CamposConstant({ dados }: { dados: NoConstant["data"] }) {
  return (
    <Campo
      id="value"
      rotulo="Valor"
      valor={dados.value}
      ajuda="Valor fixo emitido na porta `out` a cada varredura."
    />
  );
}

/** Config comum de `bus_publish`/`bus_subscribe` (ADR-042): um único componente — os dois
 *  tipos só têm `key`. Sem campo de tempo: a validade do assinante é derivada no servidor
 *  (3 × Ts do publicador, D4), não configurada aqui. */
export function CamposBusKey({ dados }: { dados: NoBusPublish["data"] | NoBusSubscribe["data"] }) {
  return (
    <div className="space-y-1">
      <Label htmlFor="key">Chave</Label>
      <Input
        id="key"
        name="key"
        data-testid="config-key"
        maxLength={64}
        defaultValue={dados.key}
        placeholder="ex.: temperatura_reator_1"
      />
      <p className="text-[10px] leading-tight text-fg-muted">
        Identifica a variável trocada entre flows pelo barramento. Só letras, números, `_` e
        `-` (até 64 caracteres); o mesmo flow ou outro flow lê o valor com esta chave em um
        bloco Barramento-Assinar.
      </p>
    </div>
  );
}
