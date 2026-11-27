import { Card } from "../../components/ui/card";
import { formatar } from "./FaceplateMalha";
import type { LoopDetailOut } from "./types";

function desligadaSeZero(v: number, sufixo = ""): string {
  return v === 0 ? "desligada" : `${formatar(v)}${sufixo}`;
}

/** Sintonia somente leitura (edição é do editor de flow) — independe de o flow estar rodando. */
export function SintoniaVigente({ config }: { config: LoopDetailOut }) {
  const sintonia = config.tuning;
  return (
    <Card className="p-4" data-testid="loop-sintonia">
      <h3 className="mb-2 text-xs text-fg-muted">Sintonia vigente (leitura)</h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {"kc" in sintonia ? (
          <>
            <dt>KC</dt>
            <dd className="process-value">{formatar(sintonia.kc)}</dd>
            <dt>TI</dt>
            <dd className="process-value">{desligadaSeZero(sintonia.ti_seconds, " s")}</dd>
            <dt>TD</dt>
            <dd className="process-value">{desligadaSeZero(sintonia.td_seconds, " s")}</dd>
            <dt>N</dt>
            <dd className="process-value">{formatar(sintonia.n)}</dd>
            <dt>BETA</dt>
            <dd className="process-value">{formatar(sintonia.beta)}</dd>
            <dt>GAMMA</dt>
            <dd className="process-value">{formatar(sintonia.gamma)}</dd>
            <dt>GAP_BAND</dt>
            <dd className="process-value">{desligadaSeZero(sintonia.gap_band)}</dd>
            <dt>GAP_GAIN</dt>
            <dd className="process-value">{formatar(sintonia.gap_gain)}</dd>
          </>
        ) : (
          <>
            <dt>KE</dt>
            <dd className="process-value">{formatar(sintonia.ke)}</dd>
            <dt>KDE</dt>
            <dd className="process-value">{desligadaSeZero(sintonia.kde)}</dd>
            <dt>KU</dt>
            <dd className="process-value">{formatar(sintonia.ku)} %/s</dd>
            <dt>TF_DE</dt>
            <dd className="process-value">{formatar(sintonia.tf_de)} s</dd>
          </>
        )}
        <dt>Ação</dt>
        <dd>{sintonia.direct_acting ? "direta" : "reversa"}</dd>
        <dt>Limites de SP</dt>
        <dd className="process-value">
          {formatar(config.sp_lo_lim)} … {formatar(config.sp_hi_lim)}
        </dd>
        <dt>Limites de saída</dt>
        <dd className="process-value">
          {formatar(config.out_lo_lim)} … {formatar(config.out_hi_lim)} %
        </dd>
        <dt>Escala de OUT</dt>
        <dd className="process-value">
          {formatar(config.out_scale_lo)} … {formatar(config.out_scale_hi)}
        </dd>
      </dl>
    </Card>
  );
}
