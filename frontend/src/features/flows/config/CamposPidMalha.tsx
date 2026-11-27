import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { NoPidLoop } from "../graph";
import { Campo } from "./CamposComuns";
import { CamposShellMalha } from "./CamposShellMalha";

/**
 * Formulário do PID Malha (ADR-039, RF-641): seção Sintonia (os 8 parâmetros do kernel + a
 * Ação) e as seções de shell completas. O sentido da malha vem SÓ de `direct_acting`: o `kc` é
 * sempre positivo no servidor (`gt=0`) — convenção diferente do bloco `pid`, onde Kc negativo
 * inverte a ação, e por isso a ajuda aqui não repete aquele texto (GLOSSARY, "Ganho (Kc)").
 */
export function CamposPidMalha({
  dados,
  portasLigadas,
}: {
  dados: NoPidLoop["data"];
  portasLigadas: ReadonlySet<string>;
}) {
  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="plaqueta text-[10px] text-fg-muted">Sintonia</legend>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 space-y-1">
            <Label htmlFor="direct_acting">Ação</Label>
            <Select
              id="direct_acting"
              name="direct_acting"
              data-testid="config-direct-acting"
              defaultValue={String(dados.direct_acting)}
            >
              <option value="false">Reversa (erro = SP − PV)</option>
              <option value="true">Direta (erro = PV − SP)</option>
            </Select>
            <p className="text-[10px] leading-tight text-fg-muted">
              Reversa: PV acima do SP reduz a saída (aquecimento, vazão). Direta: PV acima do SP
              aumenta a saída (resfriamento).
            </p>
          </div>
          <Campo
            id="kc"
            rotulo="Ganho KC (%span/EU)"
            valor={dados.kc}
            ajuda="Ganho proporcional, sempre positivo (maior que zero). O sentido da malha vem do campo Ação."
          />
          <Campo
            id="ti_seconds"
            rotulo="Tempo integral TI (0 desliga) · s"
            valor={dados.ti_seconds}
            ajuda="Tempo para a ação integral repetir o efeito proporcional."
          />
          <Campo
            id="td_seconds"
            rotulo="Tempo derivativo TD (0 desliga) · s"
            valor={dados.td_seconds}
            ajuda="Antecipa a tendência do erro."
          />
          <Campo
            id="n"
            rotulo="Filtro derivativo N (Tf = TD/N)"
            valor={dados.n}
            ajuda="Limita o ganho da derivada em altas frequências. Maior que zero."
          />
          <Campo
            id="beta"
            rotulo="Peso do SP no proporcional (BETA) · 0–1"
            valor={dados.beta}
            ajuda="1 aplica o degrau de SP inteiro no termo proporcional; menor que 1 suaviza a resposta ao SP."
          />
          <Campo
            id="gamma"
            rotulo="Peso do SP no derivativo (GAMMA) · 0–1"
            valor={dados.gamma}
            ajuda="0 deriva só a PV e evita o chute derivativo quando o SP muda em degrau."
          />
          <Campo
            id="gap_band"
            rotulo="Banda morta (meia-banda; 0 desliga) · EU"
            valor={dados.gap_band}
            ajuda="Dentro desta faixa de erro em torno do SP, o erro é atenuado pelo ganho da banda."
          />
          <Campo
            id="gap_gain"
            rotulo="Ganho dentro da banda (0–1)"
            valor={dados.gap_gain}
            ajuda="Fração do ganho aplicada enquanto o erro está dentro da banda morta."
          />
        </div>
      </fieldset>

      <CamposShellMalha dados={dados} tipo="pid_loop" portasLigadas={portasLigadas} />
    </div>
  );
}
