import { useState, type FormEvent } from "react";

import { apiResposta, ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/cn";
import { HeatmapSuperficie } from "./HeatmapSuperficie";
import { MODOS_COMANDAVEIS, percentualBarra, podeComandar, valorParaEnvio } from "./malhaLogica";
import type { LoopDetailOut, LoopState } from "./types";

export function formatar(v: number | null): string {
  return v === null ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function Barra({ rotulo, valor, minimo, maximo, ruim }: {
  rotulo: string;
  valor: number | null;
  minimo: number;
  maximo: number;
  ruim?: boolean;
}) {
  const pct = percentualBarra(valor, minimo, maximo);
  return (
    <div className="space-y-0.5" data-testid={`loop-barra-${rotulo.toLowerCase()}`}>
      <div className="flex justify-between text-xs">
        <span className={cn(ruim && "text-alarm")}>{rotulo}</span>
        <span className="process-value">{formatar(valor)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-sm bg-well">
        <div
          className={cn("h-full", ruim ? "bg-alarm" : "bg-accent")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function EscritaValor({ rotulo, habilitado, aoEnviar, minimo, maximo }: {
  rotulo: string;
  habilitado: boolean;
  aoEnviar: (v: number) => void;
  minimo: number | undefined;
  maximo: number | undefined;
}) {
  const [valor, setValor] = useState("");
  const numero = valorParaEnvio(valor);
  // Só dica: a faixa é validada pela API (o 422 aparece em `loop-erro-comando`).
  const faixa =
    minimo !== undefined && maximo !== undefined ? `Faixa ${formatar(minimo)} a ${formatar(maximo)}` : undefined;

  function enviar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    if (numero === null) return;
    aoEnviar(numero);
    setValor("");
  }

  return (
    <form onSubmit={enviar} className="flex items-end gap-2" data-testid={`loop-escrita-${rotulo}`}>
      <label className="text-xs text-fg-muted">{rotulo}</label>
      {/* text + decimal, nunca number: o input number descarta a vírgula pt-BR (CamposComuns). */}
      <input
        type="text"
        inputMode="decimal"
        title={faixa}
        disabled={!habilitado}
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        className="process-value w-24 rounded-sm border border-border bg-surface px-2 py-1 text-xs disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={!habilitado || numero === null}
        className="rounded-sm border border-border px-2 py-1 text-xs disabled:opacity-50"
      >
        Enviar
      </button>
    </form>
  );
}

/**
 * Faceplate da malha (ADR-039 §4.10): badges ALVO/REAL, botoeira de modo, barras PV/SP/OUT na
 * escala do bloco e escrita de SP/OUT (202-async: "Comandado ≠ confirmado" — o REAL só muda
 * quando o runtime confirmar via canal). Fora do ao vivo nenhum valor de `estados` é desenhado:
 * o quadro retido é de antes e não prova nada (spec §6).
 */
export function FaceplateMalha({ flowId, blockId, config, estados, aoVivo, motivoSemEstado }: {
  flowId: number;
  blockId: string;
  config: LoopDetailOut | undefined;
  estados: readonly (LoopState | undefined)[];
  aoVivo: boolean;
  motivoSemEstado: string;
}) {
  const [erroComando, setErroComando] = useState<string | null>(null);

  async function comandar(
    rota: "mode" | "sp" | "out",
    corpo: Record<string, unknown>,
  ): Promise<void> {
    setErroComando(null);
    try {
      await apiResposta(`/api/operate/${String(flowId)}/${blockId}/${rota}`, {
        method: "POST",
        body: JSON.stringify(corpo),
      });
    } catch (erro) {
      setErroComando(erro instanceof ApiError ? erro.message : "Falha ao enviar o comando");
    }
  }

  // Um único corte: daqui para baixo só `vivos` é lido, então nada retido vaza para a tela.
  // `estados` tem uma posição por canal (n_loops), definida ou não — uma seção por posição.
  const vivos = aoVivo ? estados : estados.map(() => undefined);
  const primeiro = vivos.find((estado) => estado !== undefined);
  const nLoops = estados.length;
  // A sintonia e por TIPO de malha; `type` no detalhe decide se o heatmap existe.
  const eFuzzy = config?.type === "fuzzy_loop";
  const spLo = config?.sp_lo_lim ?? 0;
  const spHi = config?.sp_hi_lim ?? 100;
  const outLo = config?.out_scale_lo ?? 0;
  const outHi = config?.out_scale_hi ?? 100;

  return (
    <div className="space-y-4" data-testid="loop-faceplate">
      <header className="flex flex-wrap items-center gap-3">
        <span className="plaqueta text-sm">{blockId}</span>
        {nLoops > 1 && (
          <Badge tone="neutral" data-testid="loop-badge-canais">
            {nLoops} CANAIS
          </Badge>
        )}
        <Badge tone="neutral" data-testid="loop-badge-target">
          ALVO {primeiro?.target.toUpperCase() ?? "—"}
        </Badge>
        <Badge
          tone={primeiro === undefined || primeiro.actual === primeiro.target ? "neutral" : "alarm"}
          data-testid="loop-badge-actual"
        >
          REAL {primeiro?.actual.toUpperCase() ?? "—"}
        </Badge>
        {vivos.some((estado) => estado !== undefined && !estado.pv_ok) && (
          <Badge tone="alarm" data-testid="loop-badge-pv-ruim">
            PV sem qualidade
          </Badge>
        )}
      </header>

      {!aoVivo && (
        <p data-testid="loop-sem-estado" className="text-sm text-fg-muted">
          {motivoSemEstado}
        </p>
      )}

      <div className="flex flex-wrap gap-2" data-testid="loop-botoeira">
        {MODOS_COMANDAVEIS.map((modo) => (
          <button
            key={modo}
            disabled={primeiro === undefined || !podeComandar(primeiro, modo)}
            data-testid={`loop-modo-${modo}`}
            onClick={() => void comandar("mode", { target: modo })}
            className={cn(
              "rounded-sm border border-border px-3 py-1.5 text-xs",
              primeiro?.target === modo && "bg-accent text-fg",
              "disabled:opacity-40",
            )}
          >
            {modo.toUpperCase()}
          </button>
        ))}
      </div>

      {vivos.map((estado, i) => (
        <section
          key={i}
          data-testid={`loop-canal-${String(i)}`}
          className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0"
        >
          {nLoops > 1 && (
            <h3 className="plaqueta text-xs text-fg-muted">Canal {String(i + 1)}</h3>
          )}
          <div className="max-w-md space-y-2">
            <Barra
              rotulo="PV"
              valor={estado?.pv ?? null}
              minimo={spLo}
              maximo={spHi}
              ruim={estado !== undefined && !estado.pv_ok}
            />
            <Barra rotulo="SP" valor={estado?.sp ?? null} minimo={spLo} maximo={spHi} />
            <Barra
              rotulo="OUT"
              valor={estado?.out ?? null}
              minimo={outLo}
              maximo={outHi}
              ruim={estado !== undefined && (estado.hi_limited || estado.lo_limited)}
            />
          </div>

          <div className="flex flex-wrap gap-6">
            {/* Sem config, sem min/max: um teto 100 provisório barraria SP válido (D6). */}
            <EscritaValor
              rotulo="SP"
              habilitado={estado?.actual === "auto"}
              aoEnviar={(v) => void comandar("sp", { value: v, channel: i })}
              minimo={config?.sp_lo_lim}
              maximo={config?.sp_hi_lim}
            />
            <EscritaValor
              rotulo="OUT (%)"
              habilitado={estado?.actual === "man"}
              aoEnviar={(v) => void comandar("out", { value: v, channel: i })}
              minimo={config?.out_lo_lim}
              maximo={config?.out_hi_lim}
            />
          </div>

          {eFuzzy && (
            <HeatmapSuperficie flowId={flowId} blockId={blockId} estado={estado} channel={i} />
          )}
        </section>
      ))}

      {erroComando !== null && (
        <p role="alert" data-testid="loop-erro-comando" className="text-sm text-alarm">
          {erroComando}
        </p>
      )}
    </div>
  );
}
