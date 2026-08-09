import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import {
  paramsPadrao,
  type DadosTfs,
  type ElementoTfs,
  type LinhaTfs,
  type MatrizTfs,
  type TipoElemento,
} from "../graph";
import { nomeParam } from "./campos";

/** Rótulos dos params por modelo (spec F3 §3.4). */
const PARAMS: Record<TipoElemento, { chave: string; rotulo: string }[]> = {
  sopdt: [
    { chave: "K", rotulo: "K (ganho)" },
    { chave: "tau1", rotulo: "tau1 (s)" },
    { chave: "tau2", rotulo: "tau2 (s)" },
    { chave: "theta", rotulo: "theta (s)" },
  ],
  iopdt: [
    { chave: "Ki", rotulo: "Ki (ganho integral)" },
    { chave: "theta", rotulo: "theta (s)" },
  ],
};

function valorParam(elemento: ElementoTfs, chave: string): number {
  const params: Record<string, number> =
    elemento.kind === "sopdt"
      ? { ...elemento.params }
      : { Ki: elemento.params.Ki, theta: elemento.params.theta };
  return params[chave] ?? 0;
}

function trocarElemento(
  matriz: MatrizTfs,
  j: number,
  k: number,
  elemento: ElementoTfs,
): MatrizTfs {
  const linha = (indice: number): LinhaTfs => {
    const atual = matriz[indice];
    return indice === j
      ? [k === 0 ? elemento : atual[0], k === 1 ? elemento : atual[1]]
      : [atual[0], atual[1]];
  };
  return [linha(0), linha(1)];
}

interface Props {
  dados: DadosTfs;
  aoMudar: (dados: DadosTfs) => void;
}

/**
 * Matriz 2x2 (spec F3 §3.4): `matrix[J][K]` é a contribuição de `uK` para `yJ`. Acima da
 * matriz, dois campos de EU (spec F6 §4.1), um por porta de saída fixa (`y1`/`y2`).
 *
 * `enabled` e `kind` são estado do modal; os params (e o EU) são campos não-controlados
 * lidos no envio (`matrizDoFormulario`/`outputEuDoFormulario`). Trocar o modelo remonta os
 * campos com os padrões do novo `kind`, e é assim que nenhum parâmetro do modelo antigo
 * sobrevive dentro de `data`.
 */
export function CamposTfs({ dados, aoMudar }: Props) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {(["y1", "y2"] as const).map((porta) => (
          <div key={porta} className="space-y-1">
            <Label htmlFor={`output_eu_${porta}`}>{porta} · EU</Label>
            <Input
              id={`output_eu_${porta}`}
              name={`output_eu_${porta}`}
              data-testid={`config-output-eu-${porta}`}
              defaultValue={dados.output_eu[porta] ?? ""}
              placeholder="ex.: C"
            />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        {dados.matrix.map((linha, j) =>
          linha.map((elemento, k) => {
            const titulo = `y${String(j + 1)} / u${String(k + 1)}`;
            return (
              <fieldset
                key={`${titulo}-${elemento.kind}`}
                className="space-y-2 rounded-panel border border-hairline bg-well p-2"
              >
                <legend className="plaqueta px-1 text-[10px] text-fg-muted">{titulo}</legend>

                <label className="flex items-center gap-2 text-xs text-fg">
                  <input
                    type="checkbox"
                    data-testid={`tfs-enabled-${String(j + 1)}${String(k + 1)}`}
                    checked={elemento.enabled}
                    onChange={(evento) => {
                      aoMudar({
                        ...dados,
                        matrix: trocarElemento(dados.matrix, j, k, {
                          ...elemento,
                          enabled: evento.target.checked,
                        }),
                      });
                    }}
                    className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                  />
                  Habilitado
                </label>

                <div className="space-y-1">
                  <Label htmlFor={`kind-${titulo}`}>Modelo</Label>
                  <Select
                    id={`kind-${titulo}`}
                    data-testid={`tfs-kind-${String(j + 1)}${String(k + 1)}`}
                    value={elemento.kind}
                    onChange={(evento) => {
                      const kind: TipoElemento = evento.target.value === "iopdt" ? "iopdt" : "sopdt";
                      const trocado: ElementoTfs =
                        kind === "sopdt"
                          ? { enabled: elemento.enabled, kind, params: paramsPadrao("sopdt") }
                          : { enabled: elemento.enabled, kind, params: paramsPadrao("iopdt") };
                      aoMudar({ ...dados, matrix: trocarElemento(dados.matrix, j, k, trocado) });
                    }}
                  >
                    <option value="sopdt">SOPDT</option>
                    <option value="iopdt">IOPDT</option>
                  </Select>
                </div>

                {PARAMS[elemento.kind].map(({ chave, rotulo }) => (
                  <div key={chave} className="space-y-1">
                    <Label htmlFor={nomeParam(j, k, chave)}>{rotulo}</Label>
                    <Input
                      id={nomeParam(j, k, chave)}
                      name={nomeParam(j, k, chave)}
                      type="text"
                      inputMode="decimal"
                      className="process-value"
                      defaultValue={String(valorParam(elemento, chave))}
                    />
                  </div>
                ))}
              </fieldset>
            );
          }),
        )}
      </div>
    </div>
  );
}
