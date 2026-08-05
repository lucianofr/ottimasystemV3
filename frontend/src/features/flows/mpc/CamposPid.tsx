import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { TagOut } from "../../../lib/api";
import type { PidMv } from "../graph";
import { nomeCampoVar, tagsPorDirecao } from "./mpcLogic";

function SelectTag({
  id,
  campo,
  varId,
  tags,
  valorAtual,
}: {
  id: string;
  campo: string;
  varId: string;
  tags: readonly TagOut[];
  valorAtual: number | null;
}) {
  return (
    <Select id={id} name={nomeCampoVar(varId, campo)} defaultValue={valorAtual ?? ""}>
      <option value="">— nenhuma —</option>
      {tags.map((tag) => (
        <option key={tag.id} value={tag.id}>
          {tag.name} ({tag.eu})
        </option>
      ))}
    </Select>
  );
}

/** Seção `pid` de uma MV (spec F4 §2.1-3, decisão A-8): tags filtradas por direção —
 *  write/mode_cmd exigem tag de escrita (W), readback/mode_read exigem leitura (R). Campos
 *  não-controlados, lidos pelo `id` da MV no Aplicar (`variavelMvDoFormulario`). */
export function CamposPid({
  varId,
  pid,
  tags,
}: {
  varId: string;
  pid: PidMv | null;
  tags: readonly TagOut[];
}) {
  const tagsW = tagsPorDirecao(tags, "w");
  const tagsR = tagsPorDirecao(tags, "r");
  const c = (campo: string): string => `pid-${varId}-${campo}`;

  return (
    <div className="grid grid-cols-2 gap-3 border-t border-hairline pt-2">
      <div className="space-y-1">
        <Label htmlFor={c("write")}>Tag de escrita (W)</Label>
        <SelectTag
          id={c("write")}
          campo="pid_write_tag_id"
          varId={varId}
          tags={tagsW}
          valorAtual={pid?.write_tag_id ?? null}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={c("readback")}>Tag de readback (R)</Label>
        <SelectTag
          id={c("readback")}
          campo="pid_readback_tag_id"
          varId={varId}
          tags={tagsR}
          valorAtual={pid?.readback_tag_id ?? null}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={c("mode-cmd")}>Tag de modo — comando (W)</Label>
        <SelectTag
          id={c("mode-cmd")}
          campo="pid_mode_cmd_tag_id"
          varId={varId}
          tags={tagsW}
          valorAtual={pid?.mode_cmd_tag_id ?? null}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={c("mode-read")}>Tag de modo — leitura (R, opcional)</Label>
        <SelectTag
          id={c("mode-read")}
          campo="pid_mode_read_tag_id"
          varId={varId}
          tags={tagsR}
          valorAtual={pid?.mode_read_tag_id ?? null}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={c("target-mode")}>Modo alvo</Label>
        <Select
          id={c("target-mode")}
          name={nomeCampoVar(varId, "pid_target_mode")}
          defaultValue={pid?.target_mode ?? "rcas"}
        >
          <option value="rcas">RCAS</option>
          <option value="cas">CAS</option>
          <option value="rout">ROUT</option>
        </Select>
      </div>
      <div />
      <div className="space-y-1">
        <Label htmlFor={c("mode-auto")}>Valor do modo — devolver (auto)</Label>
        <Input
          id={c("mode-auto")}
          name={nomeCampoVar(varId, "pid_mode_auto")}
          type="text"
          inputMode="decimal"
          className="process-value"
          defaultValue={String(pid?.mode_values.auto ?? 0)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={c("mode-target")}>Valor do modo — assumir (target)</Label>
        <Input
          id={c("mode-target")}
          name={nomeCampoVar(varId, "pid_mode_target")}
          type="text"
          inputMode="decimal"
          className="process-value"
          defaultValue={String(pid?.mode_values.target ?? 0)}
        />
      </div>
    </div>
  );
}
