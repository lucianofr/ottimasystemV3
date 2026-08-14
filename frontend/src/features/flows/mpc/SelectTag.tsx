import { Select } from "../../../components/ui/select";
import type { TagOut } from "../../../lib/api";
import { nomeCampoVar } from "./mpcLogic";

/** Select de tag do projeto (já filtrada por direção pelo chamador), não-controlado: lido
 *  pelo `name` no Aplicar — mesmo padrão dos demais campos do modal. Opção vazia = "sem
 *  tag" (o builder traduz para `null`). Extraído de `CamposPid` para servir também ao SP
 *  remoto da CV (RF-614). */
export function SelectTag({
  id,
  campo,
  varId,
  tags,
  valorAtual,
  testid,
}: {
  id: string;
  campo: string;
  varId: string;
  tags: readonly TagOut[];
  valorAtual: number | null;
  testid?: string;
}) {
  return (
    <Select
      id={id}
      name={nomeCampoVar(varId, campo)}
      defaultValue={valorAtual ?? ""}
      data-testid={testid}
    >
      <option value="">— nenhuma —</option>
      {tags.map((tag) => (
        <option key={tag.id} value={tag.id}>
          {tag.name} ({tag.eu})
        </option>
      ))}
    </Select>
  );
}
