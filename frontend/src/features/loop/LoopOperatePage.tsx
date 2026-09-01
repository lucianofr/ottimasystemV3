import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";

import { useAssinatura, useCanalAoVivo } from "../../app/CanalAoVivo";
import { apiResposta, ApiError } from "../../lib/api";
import type { LoopState } from "../../lib/contracts.gen";
import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { cn } from "../../lib/cn";
import { HeatmapSuperficie } from "./HeatmapSuperficie";
import { rotuloLoop, useLoops, useLoopConfig } from "./useLoops";
import type { LoopNodeOut } from "./types";

/**
 * PID MALHA (ADR-039 §4.10) — faceplate mínimo de operação: combobox da malha do projeto
 * ativo (`?flow=&bloco=` em query string, mesmo padrão de `FuzzyOperatePage`), badges
 * ALVO/REAL, botoeira de modo, barras PV/SP/OUT ao vivo (`loop_state`), escrita de SP/OUT
 * (202-async: "Comandado ≠ confirmado" — o ALVO muda na hora, o REAL só quando o runtime
 * confirmar via canal) e aba de sintonia somente leitura (edição é do editor de flow).
 */

export const MODOS_LOOP = ["oos", "iman", "lo", "man", "auto", "cas", "rcas", "rout"] as const;
export type ModoLoop = (typeof MODOS_LOOP)[number];

/** Modos que o operador pode COMANDAR (os demais existem no FF mas são atingidos por
 *  rebaixamento/cascata — a API também só aceita estes). */
const MODOS_COMANDAVEIS: readonly ModoLoop[] = ["oos", "man", "auto", "cas", "rcas", "rout"];

/** Modo comandável está em `permitted`? Pura para check. */
export function podeComandar(estado: LoopState, modo: ModoLoop): boolean {
  return MODOS_COMANDAVEIS.includes(modo) && estado.permitted.includes(modo);
}

function chaveNo(no: LoopNodeOut): string {
  return `${String(no.flow_id)}/${no.block_id}`;
}

function formatar(v: number | null): string {
  return v === null ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function Barra({ rotulo, valor, minimo, maximo, ruim }: {
  rotulo: string;
  valor: number | null;
  minimo: number;
  maximo: number;
  ruim?: boolean;
}) {
  const pct =
    valor === null || maximo <= minimo
      ? 0
      : Math.max(0, Math.min(100, ((valor - minimo) / (maximo - minimo)) * 100));
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
  minimo: number;
  maximo: number;
}) {
  const [valor, setValor] = useState("");

  function enviar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const numero = Number(valor);
    if (!Number.isFinite(numero)) return;
    aoEnviar(numero);
    setValor("");
  }

  return (
    <form onSubmit={enviar} className="flex items-end gap-2" data-testid={`loop-escrita-${rotulo}`}>
      <label className="text-xs text-fg-muted">{rotulo}</label>
      <input
        type="number"
        step="any"
        min={minimo}
        max={maximo}
        disabled={!habilitado}
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        className="process-value w-24 rounded-sm border border-border bg-surface px-2 py-1 text-xs disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={!habilitado}
        className="rounded-sm border border-border px-2 py-1 text-xs disabled:opacity-50"
      >
        Enviar
      </button>
    </form>
  );
}

function LoopResolvido({ flowId, blockId }: { flowId: number; blockId: string }) {
  useAssinatura({ loop_state: [`${String(flowId)}/${blockId}`] });
  const canal = useCanalAoVivo();
  const estado = canal.loopStates.get(`${String(flowId)}/${blockId}`);
  const config = useLoopConfig(flowId, blockId);
  const [erroComando, setErroComando] = useState<string | null>(null);

  async function comandar(rota: "mode" | "sp" | "out", corpo: Record<string, unknown>): Promise<void> {
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

  if (estado === undefined) {
    return (
      <Card className="max-w-lg p-6" data-testid="loop-aguardando">
        <p className="text-sm text-fg-muted">
          Aguardando estado da malha (o bloco precisa estar rodando)…
        </p>
      </Card>
    );
  }

  const sintonia = config.data?.tuning;
  // A sintonia e por TIPO de malha (o backend devolve uma das duas formas); `type` no
  // detalhe e o discriminante — tambem decide se a aba de superficie existe.
  const eFuzzy = config.data?.type === "fuzzy_loop";

  return (
    <div className="space-y-4 p-4" data-testid="loop-faceplate">
      <header className="flex flex-wrap items-center gap-3">
        <span className="plaqueta text-sm">{blockId}</span>
        <Badge tone="neutral" data-testid="loop-badge-target">
          ALVO {estado.target.toUpperCase()}
        </Badge>
        <Badge
          tone={estado.actual === estado.target ? "neutral" : "alarm"}
          data-testid="loop-badge-actual"
        >
          REAL {estado.actual.toUpperCase()}
        </Badge>
        {!estado.pv_ok && (
          <Badge tone="alarm" data-testid="loop-badge-pv-ruim">
            PV sem qualidade
          </Badge>
        )}
      </header>

      <div className="flex flex-wrap gap-2" data-testid="loop-botoeira">
        {MODOS_COMANDAVEIS.map((modo) => (
          <button
            key={modo}
            disabled={!podeComandar(estado, modo)}
            data-testid={`loop-modo-${modo}`}
            onClick={() => void comandar("mode", { target: modo })}
            className={cn(
              "rounded-sm border border-border px-3 py-1.5 text-xs",
              estado.target === modo && "bg-accent text-fg",
              "disabled:opacity-40",
            )}
          >
            {modo.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="max-w-md space-y-2">
        <Barra rotulo="PV" valor={estado.pv} minimo={0} maximo={100} ruim={!estado.pv_ok} />
        <Barra rotulo="SP" valor={estado.sp} minimo={0} maximo={100} />
        <Barra
          rotulo="OUT"
          valor={estado.out}
          minimo={0}
          maximo={100}
          ruim={estado.hi_limited || estado.lo_limited}
        />
      </div>

      <div className="flex flex-wrap gap-6">
        <EscritaValor
          rotulo="SP"
          habilitado={estado.actual === "auto"}
          aoEnviar={(v) => void comandar("sp", { value: v })}
          minimo={0}
          maximo={100}
        />
        <EscritaValor
          rotulo="OUT (%)"
          habilitado={estado.actual === "man"}
          aoEnviar={(v) => void comandar("out", { value: v })}
          minimo={0}
          maximo={100}
        />
      </div>

      {erroComando !== null && (
        <p role="alert" data-testid="loop-erro-comando" className="text-sm text-alarm">
          {erroComando}
        </p>
      )}

      {sintonia !== undefined && (
        <Card className="max-w-md p-4" data-testid="loop-sintonia">
          <h3 className="mb-2 text-xs text-fg-muted">Sintonia vigente (leitura)</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {"kc" in sintonia ? (
              <>
                <dt>KC</dt>
                <dd className="process-value">{formatar(sintonia.kc)}</dd>
                <dt>TI</dt>
                <dd className="process-value">
                  {sintonia.ti_seconds === 0 ? "desligada" : `${formatar(sintonia.ti_seconds)} s`}
                </dd>
                <dt>TD</dt>
                <dd className="process-value">
                  {sintonia.td_seconds === 0 ? "desligada" : `${formatar(sintonia.td_seconds)} s`}
                </dd>
              </>
            ) : (
              <>
                <dt>KE</dt>
                <dd className="process-value">{formatar(sintonia.ke)}</dd>
                <dt>KDE</dt>
                <dd className="process-value">
                  {sintonia.kde === 0 ? "desligada" : formatar(sintonia.kde)}
                </dd>
                <dt>KU</dt>
                <dd className="process-value">{formatar(sintonia.ku)} %/s</dd>
                <dt>TF_DE</dt>
                <dd className="process-value">{formatar(sintonia.tf_de)} s</dd>
              </>
            )}
            <dt>Ação</dt>
            <dd>{sintonia.direct_acting ? "direta" : "reversa"}</dd>
          </dl>
        </Card>
      )}

      {eFuzzy && <HeatmapSuperficie flowId={flowId} blockId={blockId} estado={estado} />}
    </div>
  );
}

export function LoopOperatePage() {
  const [params] = useSearchParams();
  const loops = useLoops();

  if (loops.isPending) {
    return (
      <Card className="m-4 max-w-lg p-6">
        <p className="text-sm text-fg-muted">Carregando…</p>
      </Card>
    );
  }
  if (loops.isError) {
    return (
      <Card className="m-4 max-w-lg p-6">
        <p role="alert" className="text-sm text-alarm">
          Falha ao listar as malhas do projeto ativo
        </p>
      </Card>
    );
  }
  if (loops.data.length === 0) {
    return (
      <Card className="m-4 max-w-lg p-6">
        <p className="text-sm text-fg-muted">
          Nenhuma malha no projeto ativo — arraste um bloco PID Malha no editor de flow.
        </p>
      </Card>
    );
  }

  const flowSel = params.get("flow");
  const blocoSel = params.get("bloco");
  const selecionada =
    flowSel !== null && blocoSel !== null
      ? loops.data.find((no) => String(no.flow_id) === flowSel && no.block_id === blocoSel)
      : undefined;

  if (selecionada === undefined) {
    return (
      <div className="m-4 max-w-md space-y-2" data-testid="loop-selecao">
        <h2 className="text-sm">Operar malha</h2>
        <Select
          data-testid="loop-combobox"
          value=""
          onChange={(e) => {
            const chave = e.target.value;
            if (chave === "") return;
            const no = loops.data.find((n) => chaveNo(n) === chave);
            if (no !== undefined) {
              params.set("flow", String(no.flow_id));
              params.set("bloco", no.block_id);
            }
          }}
        >
          <option value="">Escolha a malha…</option>
          {loops.data.map((no) => (
            <option key={chaveNo(no)} value={chaveNo(no)}>
              {rotuloLoop(no)}
            </option>
          ))}
        </Select>
      </div>
    );
  }

  return (
    <LoopResolvido
      key={chaveNo(selecionada)}
      flowId={selecionada.flow_id}
      blockId={selecionada.block_id}
    />
  );
}
