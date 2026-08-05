import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { tsMpcDerivado } from "./mpcLogic";

interface Props {
  nome: string;
  multiplier: number;
  tsFlowSegundos: number;
  aoMudarMultiplier: (multiplier: number) => void;
}

/** Aba Geral (spec F4 §7.3): nome, multiplicador (inteiro >= 1) e `Ts_mpc` derivado, exibido
 *  read-only — `multiplier` é o único campo controlado aqui: a derivação precisa acompanhar
 *  cada dígito digitado. `nome` fica não-controlado (lido do formulário no Aplicar, como o
 *  `label`/`exec_order` do modal genérico) por não ter dependente ao vivo. */
export function TabGeneral({ nome, multiplier, tsFlowSegundos, aoMudarMultiplier }: Props) {
  return (
    <div data-testid="mpc-tab-geral" className="space-y-4">
      <div className="space-y-1">
        <Label htmlFor="mpc-name">Nome</Label>
        <Input id="mpc-name" name="mpc_name" maxLength={80} defaultValue={nome} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="mpc-multiplier">Multiplicador</Label>
          <Input
            id="mpc-multiplier"
            name="mpc_multiplier"
            type="number"
            min={1}
            step={1}
            className="process-value"
            value={multiplier}
            onChange={(evento) => {
              const valor = Math.max(1, Math.trunc(Number(evento.target.value) || 1));
              aoMudarMultiplier(valor);
            }}
          />
          <p className="text-[10px] text-fg-muted">
            Fronteira de execução do MPC: a cada {multiplier} varredura(s) do flow (RF-603).
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="mpc-ts">Ts_mpc (derivado)</Label>
          <Input
            id="mpc-ts"
            data-testid="mpc-ts-derivado"
            readOnly
            disabled
            className="process-value"
            value={`${String(tsMpcDerivado(multiplier, tsFlowSegundos))} s`}
          />
          <p className="text-[10px] text-fg-muted">
            multiplier × Ts_flow — nunca editado diretamente (RF-603).
          </p>
        </div>
      </div>
    </div>
  );
}
