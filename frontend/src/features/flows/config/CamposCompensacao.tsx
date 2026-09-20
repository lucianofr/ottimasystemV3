import { type NoDeadTime, type NoLeadLag } from "../graph";
import { Campo } from "./CamposComuns";

/**
 * Formulários dos blocos de compensação dinâmica Lead-Lag e Tempo morto.
 *
 * Mesma disciplina de `CamposUtilitarios.tsx`: campos não-controlados lidos no envio por
 * `numeroDoCampo` (vírgula decimal pt-BR).
 */

export function CamposLeadLag({ dados }: { dados: NoLeadLag["data"] }) {
  return (
    <div className="space-y-3">
      <Campo
        id="gain"
        rotulo="Ganho"
        valor={dados.gain}
        ajuda="Multiplica a saída. Aceita valor negativo: um distúrbio que empurra a variável controlada para cima costuma pedir correção para baixo. Zero desliga a compensação sem remover o bloco."
      />
      <div className="grid grid-cols-2 gap-3">
        <Campo
          id="tau_lead"
          rotulo="τ avanço (s)"
          valor={dados.tau_lead}
          ajuda="Constante de tempo do numerador. Zero reduz o bloco a um filtro de 1ª ordem."
        />
        <Campo
          id="tau_lag"
          rotulo="τ atraso (s)"
          valor={dados.tau_lag}
          ajuda="Constante de tempo do denominador; precisa ser maior que zero. O ganho do bloco em alta frequência é Ganho × (τ avanço / τ atraso), e essa razão avanço/atraso está limitada a 10 — acima disso, ligue dois blocos em série."
        />
      </div>
    </div>
  );
}

export function CamposDeadTime({ dados }: { dados: NoDeadTime["data"] }) {
  return (
    <Campo
      id="theta"
      rotulo="Tempo morto θ (s)"
      valor={dados.theta}
      ajuda="Atraso puro de transporte, contado em varreduras do flow (θ dividido pelo Ts, arredondado). Até meio Ts (inclusive) o bloco vira passagem direta."
    />
  );
}
