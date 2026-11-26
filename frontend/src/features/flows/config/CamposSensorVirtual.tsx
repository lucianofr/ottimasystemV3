import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { MAX_ENTRADAS_SENSOR_VIRTUAL, type NoSensorVirtual } from "../graph";

const OPCOES_ENTRADAS = Array.from({ length: MAX_ENTRADAS_SENSOR_VIRTUAL }, (_, i) => i + 1);

/**
 * Formulário dos três blocos de sensor virtual (RF-581, ADR-046): número de entradas e a
 * unidade da saída. Campos não-controlados lidos no envio — o `output_eu` é UMA string, não o
 * mapa por porta do Script/Fuzzy. O modelo não é escolhido aqui (SPEC_SENSOR_VIRTUAL §5.1).
 */
export function CamposSensorVirtual({ dados }: { dados: NoSensorVirtual["data"] }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="n_inputs">Número de entradas</Label>
          <Select id="n_inputs" name="n_inputs" data-testid="config-n-inputs" defaultValue={dados.n_inputs}>
            {OPCOES_ENTRADAS.map((quantidade) => (
              <option key={quantidade} value={quantidade}>
                {quantidade}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="output_eu">Unidade da saída</Label>
          <Input
            id="output_eu"
            name="output_eu"
            data-testid="config-output-eu"
            defaultValue={dados.output_eu}
            placeholder="ex.: ppm"
          />
        </div>
      </div>
      <p className="text-[10px] leading-tight text-fg-muted">
        O modelo é escolhido na página Coleta e treino, não aqui.
      </p>
    </div>
  );
}
