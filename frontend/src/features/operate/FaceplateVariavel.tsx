import { useEffect, useState } from "react";

import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { api, ApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import type { MpcState } from "../../lib/contracts.gen";
import { clampNaFaixa, type Faixa } from "./clamp";
import { reduzirPendencia, type Pendencia } from "./pendencia";

/**
 * Faceplate de variável — tarefa 4.4 do plano F5b (spec F5 §7.4-5; RF-702/704). Um por
 * MV/CV/Restrição/DV: barra vertical com escala demarcada (`limits`/`sp_limits`/`range`,
 * DESIGN §Shapes — convenção intocável) + PV grande em mono tabular + EU (DESIGN §Typography,
 * "A Regra do Número Tabular").
 *
 * Regras de edição por tipo:
 * - CV: SP editável só com `modes.man_auto === "auto"`; fora disso o campo mostra o valor
 *   publicado (SP rastreado / PV-tracking) desabilitado e dessaturado.
 * - MV: editável só com `modes.local_remote === "remote" && modes.man_auto === "man"`; fora
 *   do modo, campo desabilitado exibindo o valor publicado (`v`).
 * - Restrição/DV: somente leitura, nunca renderizam campo de escrita.
 *
 * Toda escrita (`POST /sp`|`/mv`) abre uma pendência via `reduzirPendencia` (4.2, mesma
 * mecânica do faceplate principal 4.3): o controle mostra o valor comandado em fantasma com
 * outline azul até o próximo `mpc.state.vars[id]` confirmar (materializa) ou a janela
 * `max(3×Ts_mpc, 5s)` vencer (reverte) — nunca finge que o comando já valeu (RNF-05).
 */

export type VariavelTipo = "mv" | "cv" | "constraint" | "dv";

export type FaceplateVariavelProps = {
  tipo: VariavelTipo;
  definicao: {
    id: string;
    name: string;
    eu: string;
    limits?: Faixa | null;
    sp_limits?: Faixa | null;
    range?: { low: number; high: number } | null;
    du_max?: number | null;
  };
  valor: { v: number; sp?: number | null } | undefined;
  modos: { local_remote: "local" | "remote"; man_auto: "man" | "auto" };
  flowId: number;
  blockId: string;
  tsMpcSegundos: number;
};

const ROTULO_TIPO: Record<VariavelTipo, string> = {
  mv: "MV",
  cv: "CV",
  constraint: "Restrição",
  dv: "DV",
};

/** Faixa da escala: `limits` (MV) / `sp_limits` (CV) já chegam como `{min,max}` (schema
 *  `Limits` do backend, sem conversão); `range` da Restrição é `{low,high}` — normalizado
 *  aqui só para alimentar a mesma barra. DV não tem faixa publicada (`DvOut` não traz
 *  `limits`/`range`): sem dado para demarcar, a barra não é desenhada — só PV + EU. */
function faixaDaEscala(props: FaceplateVariavelProps): Faixa | null {
  if (props.tipo === "mv") return props.definicao.limits ?? null;
  if (props.tipo === "cv") return props.definicao.sp_limits ?? null;
  if (props.tipo === "constraint") {
    const range = props.definicao.range;
    return range ? { min: range.low, max: range.high } : null;
  }
  return null;
}

/** Barra vertical de instrumento (DESIGN §Shapes): escala com 10% de folga além da faixa
 *  publicada dos dois lados, para um PV fora dos limites ainda aparecer deslocado na barra em
 *  vez de grudado na borda — não é vocabulário do MPC, é só o mapeamento valor→posição desta
 *  barra específica. */
function percentualNaBarra(valor: number, faixa: Faixa): number {
  const largura = faixa.max - faixa.min;
  const margem = largura > 0 ? largura * 0.1 : 1;
  const fracao = (valor - (faixa.min - margem)) / (largura + 2 * margem);
  return Math.min(100, Math.max(0, fracao * 100));
}

function BarraVertical({
  faixa,
  pv,
  sp,
  testId,
}: {
  faixa: Faixa;
  pv: number | undefined;
  sp: number | null | undefined;
  testId: string;
}) {
  const pvPercentual = pv !== undefined ? percentualNaBarra(pv, faixa) : null;
  const spPercentual = sp !== null && sp !== undefined ? percentualNaBarra(sp, faixa) : null;
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="process-value text-[10px] text-fg-muted">{faixa.max.toFixed(2)}</span>
      <div className="relative h-32 w-4 rounded-panel border border-hairline bg-well" data-testid={testId}>
        {pvPercentual !== null && (
          <div className="absolute inset-x-0 bottom-0 bg-fg-muted/30" style={{ height: `${String(pvPercentual)}%` }} />
        )}
        {pvPercentual !== null && (
          <div
            className="absolute inset-x-0 h-px bg-fg"
            style={{ bottom: `${String(pvPercentual)}%` }}
            data-testid={`${testId}-pv`}
          />
        )}
        {spPercentual !== null && (
          <div
            className="absolute inset-x-0 h-0.5 bg-accent"
            style={{ bottom: `${String(spPercentual)}%` }}
            data-testid={`${testId}-sp`}
          />
        )}
      </div>
      <span className="process-value text-[10px] text-fg-muted">{faixa.min.toFixed(2)}</span>
    </div>
  );
}

export default function FaceplateVariavel(props: FaceplateVariavelProps) {
  const { tipo, definicao, valor, modos, flowId, blockId, tsMpcSegundos } = props;
  const faixa = faixaDaEscala(props);
  const campoComandado = tipo === "mv" ? "v" : "sp";
  const alvo = `vars.${definicao.id}.${campoComandado}`;

  const [pendencia, setPendencia] = useState<Pendencia | null>(null);
  const [rascunho, setRascunho] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // "tique": expira a pendência vencida mesmo sem `mpc.state` novo (flow parado, aba em foco
  // sem tráfego) — mesmo relógio de UI que 4.3 dispara para o faceplate principal.
  useEffect(() => {
    const id = window.setInterval(() => {
      setPendencia((atual) => reduzirPendencia(atual, { tipo: "tique", agora: Date.now() }));
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, []);

  // "estadoPublicado": cada `valor` novo (mpc.state.vars[id] republicado) tenta materializar a
  // pendência. `lerCaminho` (pendencia.ts) só lê `vars.<id>.<campo>` do objeto abaixo — o resto
  // do shape de `MpcState` nunca é acessado, então o cast não finge um estado completo real.
  useEffect(() => {
    if (valor === undefined) return;
    const estadoMinimo = { vars: { [definicao.id]: valor } } as unknown as MpcState;
    setPendencia((atual) =>
      reduzirPendencia(atual, { tipo: "estadoPublicado", state: estadoMinimo, agora: Date.now() }),
    );
  }, [valor, definicao.id]);

  const pendenciaAtiva = pendencia !== null && pendencia.alvo === alvo ? pendencia : null;

  const editavel =
    tipo === "mv"
      ? modos.local_remote === "remote" && modos.man_auto === "man"
      : tipo === "cv"
        ? modos.man_auto === "auto"
        : false;

  async function enviar(): Promise<void> {
    if (!editavel || rascunho === null || faixa === null) return;
    const bruto = Number(rascunho.replace(",", "."));
    if (!Number.isFinite(bruto)) {
      setErro("Valor inválido");
      return;
    }
    const alvoValor = clampNaFaixa(bruto, faixa);
    setErro(null);
    try {
      const caminho = tipo === "mv" ? "mv" : "sp";
      await api(`/api/operate/${String(flowId)}/${blockId}/${caminho}`, {
        method: "POST",
        body: JSON.stringify({ var_id: definicao.id, value: alvoValor }),
      });
      setPendencia(
        reduzirPendencia(pendencia, {
          tipo: "comandar",
          alvo,
          valor: alvoValor,
          tsMpcSegundos,
          agora: Date.now(),
        }),
      );
      setRascunho(null);
    } catch (motivo) {
      setErro(motivo instanceof ApiError ? motivo.message : "Falha ao enviar comando");
    }
  }

  const valorPublicadoTexto =
    tipo === "mv"
      ? valor?.v !== undefined
        ? valor.v.toFixed(2)
        : ""
      : valor?.sp != null
        ? valor.sp.toFixed(2)
        : "";
  const valorInput = rascunho ?? (pendenciaAtiva !== null ? String(pendenciaAtiva.valorComandado) : valorPublicadoTexto);

  return (
    <Card
      className="flex w-40 shrink-0 flex-col gap-2 p-3"
      data-testid={`faceplate-${tipo}-${definicao.id}`}
      data-var-id={definicao.id}
      data-pendente={pendenciaAtiva !== null ? "true" : "false"}
    >
      <div>
        <Label className="block">{ROTULO_TIPO[tipo]}</Label>
        <p className="truncate text-sm text-fg" title={definicao.name}>
          {definicao.name}
        </p>
      </div>

      <div className="flex items-end justify-center gap-3">
        {faixa !== null && (
          <BarraVertical
            faixa={faixa}
            pv={valor?.v}
            sp={tipo === "cv" ? (valor?.sp ?? null) : null}
            testId={`faceplate-escala-${definicao.id}`}
          />
        )}
        <div className="text-right">
          <p className="process-value text-2xl leading-none" data-testid={`faceplate-pv-${definicao.id}`}>
            {valor?.v !== undefined ? valor.v.toFixed(2) : "—"}
          </p>
          <p className="text-xs text-fg-muted">{definicao.eu}</p>
        </div>
      </div>

      {(tipo === "mv" || tipo === "cv") && (
        <div>
          <Label htmlFor={`faceplate-${tipo === "mv" ? "mv" : "sp"}-input-${definicao.id}`}>
            {tipo === "mv" ? "MV" : "SP"}
          </Label>
          <Input
            id={`faceplate-${tipo === "mv" ? "mv" : "sp"}-input-${definicao.id}`}
            data-testid={`faceplate-${tipo === "mv" ? "mv" : "sp"}-input-${definicao.id}`}
            className={cn(
              "process-value",
              !editavel && "text-fg-muted",
              pendenciaAtiva !== null && "border-accent text-fg-muted",
            )}
            disabled={!editavel}
            value={valorInput}
            onChange={(evento) => {
              setErro(null);
              setRascunho(evento.target.value);
            }}
            onBlur={() => {
              void enviar();
            }}
            onKeyDown={(evento) => {
              if (evento.key === "Enter") evento.currentTarget.blur();
              if (evento.key === "Escape") {
                setRascunho(null);
                evento.currentTarget.blur();
              }
            }}
          />
        </div>
      )}

      {erro !== null && (
        <p role="alert" data-testid={`faceplate-erro-${definicao.id}`} className="text-xs text-alarm">
          {erro}
        </p>
      )}
    </Card>
  );
}
