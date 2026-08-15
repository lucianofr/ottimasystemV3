import type { NoPid } from "../graph";
import { Campo } from "./CamposComuns";

/**
 * Formulário do bloco PID (RF-551..554, ADR-031). Os dez campos ficam sempre visíveis — nenhum
 * gate outro campo (ao contrário do TFS, onde `enabled`/`kind` decidem o que existe) — então o
 * formulário não carrega estado de React, só lê o FormData no envio, igual aos filtros
 * (`CamposFiltros.tsx`). O campo numérico é o compartilhado de `CamposComuns.tsx`; os limites
 * de saída passam `valor={null}` quando em branco (sem limite) e ganham placeholder.
 *
 * Três grupos (Ganhos, Setpoint e saída, Estrutura) para os dez campos caberem sem virar uma
 * parede de rótulos: cada um é uma decisão de sintonia diferente, e a `ajuda` é parte do
 * contrato de usabilidade da janela — aqui ela substitui a folha de dados do instrumento que o
 * engenheiro não tem em mãos.
 *
 * `CamposBlocoPid` (não `CamposPid`) porque `mpc/CamposPid.tsx` já existe e é outra coisa: o
 * binding de tags PLC-PID por MV do MPC (spec F4 §2.1-3), sem relação com este bloco.
 */

function CampoBooleano({
  id,
  rotulo,
  valor,
  ajuda,
}: {
  id: string;
  rotulo: string;
  valor: boolean;
  ajuda: string;
}) {
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 text-xs text-fg" htmlFor={id}>
        <input
          type="checkbox"
          id={id}
          name={id}
          data-testid={`config-${id.replace(/_/g, "-")}`}
          defaultChecked={valor}
          className="h-3.5 w-3.5 accent-[var(--color-accent)]"
        />
        {rotulo}
      </label>
      <p className="text-[10px] leading-tight text-fg-muted">{ajuda}</p>
    </div>
  );
}

export function CamposBlocoPid({ dados }: { dados: NoPid["data"] }) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h3 className="plaqueta text-[10px] text-fg-muted">Ganhos</h3>
        <div className="grid grid-cols-2 gap-3">
          <Campo
            id="kc"
            rotulo="Ganho Kc"
            valor={dados.kc}
            ajuda="Ganho proporcional (forma ISA). Negativo inverte a ação — ação reversa, quando aumentar a saída deve diminuir a variável de processo."
          />
          <Campo
            id="ti_seconds"
            rotulo="Tempo integral Ti (s/repetição)"
            valor={dados.ti_seconds}
            ajuda="Tempo para a ação integral repetir o efeito proporcional. Zero desliga a ação integral (reset, em repetições por segundo, é 1/Ti)."
          />
          <Campo
            id="td_seconds"
            rotulo="Tempo derivativo Td (s)"
            valor={dados.td_seconds}
            ajuda="Antecipa a tendência do erro. Zero desliga a ação derivativa."
          />
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="plaqueta text-[10px] text-fg-muted">Setpoint e saída</h3>
        <div className="grid grid-cols-2 gap-3">
          <Campo
            id="setpoint"
            rotulo="Setpoint (EU)"
            valor={dados.setpoint}
            ajuda="Valor alvo quando a porta sp não está conectada. Conectada, o valor recebido na porta substitui este campo."
          />
          <Campo
            id="starting_output"
            rotulo="Saída inicial (EU)"
            valor={dados.starting_output}
            ajuda="Semente bumpless aplicada no deploy ou ao sair de parado — evita um degrau na saída ao ligar o controlador."
          />
          <Campo
            id="output_min"
            rotulo="Saída mínima (EU)"
            valor={dados.output_min}
            placeholder="sem limite"
            ajuda="Em branco, sem limite inferior. Os limites também travam a ação integral (anti-windup)."
          />
          <Campo
            id="output_max"
            rotulo="Saída máxima (EU)"
            valor={dados.output_max}
            placeholder="sem limite"
            ajuda="Em branco, sem limite superior. Os limites também travam a ação integral (anti-windup)."
          />
        </div>
      </div>

      {/* fieldset/legend e não div/h3: os três booleanos são um grupo, e o leitor de tela
          precisa anunciar "Estrutura" como contexto de cada caixa (mesmo padrão do TFS). */}
      <fieldset className="space-y-2">
        <legend className="plaqueta text-[10px] text-fg-muted">Estrutura</legend>
        <div className="grid grid-cols-2 gap-3">
          <CampoBooleano
            id="auto_mode"
            rotulo="Modo automático"
            valor={dados.auto_mode}
            ajuda="Desligado, o PID congela e a saída fica no último valor calculado — útil para transferência manual."
          />
          <CampoBooleano
            id="proportional_on_measurement"
            rotulo="P sobre a medição"
            valor={dados.proportional_on_measurement}
            ajuda="Calcula a parte proporcional sobre a variação da medição em vez do erro — evita o degrau de saída (overshoot) quando o setpoint muda."
          />
          <CampoBooleano
            id="differential_on_measurement"
            rotulo="D sobre a medição"
            valor={dados.differential_on_measurement}
            ajuda="Calcula a derivada sobre a medição em vez do erro — evita o chute derivativo (derivative kick) quando o setpoint muda em degrau."
          />
        </div>
      </fieldset>
    </div>
  );
}
