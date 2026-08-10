import { useEffect, useReducer, useState } from "react";

import { Card } from "../../components/ui/card";
import { api, ApiError } from "../../lib/api";
import type { FlowStatus, MpcModes, MpcState } from "../../lib/contracts.gen";
import { cn } from "../../lib/cn";
import { ROTULO_ESTADO, formatarNumero, type EstadoFlow } from "../flows/useFlowStatus";
import { reduzirPendencia, type Pendencia } from "./pendencia";
import { RelogioAgora } from "./RelogioAgora";
import type { MpcNodeOut } from "./useMpcs";

/**
 * Faceplate principal do MPC (spec F5 §7.4-3; ADR-010; RF-701/704; plano F5b tarefa 4.3):
 * plaqueta `nome · flow`, comutadores de posição LOCAL/REMOTO e MAN/AUTO (MAN/AUTO só
 * renderiza em REMOTO — ADR-010), 3 lâmpadas (flow, solver, input_valid — Regra do Canal
 * Redundante) e contadores `overruns`/`last_solve_ms` em mono tabular (Regra do Número
 * Tabular). Comando de modo via `POST /api/operate/{fid}/{bid}/mode`, pendente-até-confirmar
 * com o redutor puro `reduzirPendencia` (tarefa 4.2).
 */

type Solver = MpcState["status"]["solver"];
type PosicaoLocalRemoto = MpcModes["local_remote"];
type PosicaoManAuto = MpcModes["man_auto"];

const ROTULO_SOLVER: Record<Solver, string> = {
  ok: "Ok",
  building: "Build em andamento",
  overrun: "Overrun",
  error: "Falha",
  idle: "Ocioso",
};

/** Cores de severidade (DESIGN.md §Colors): "falha (…solver)" ⇒ alarme; "overrun,
 *  qualidade degradada, estados pendentes de atenção" ⇒ advertência (cobre também
 *  `building`, a partida esperada do deploy — §6.2). */
const COR_SOLVER: Record<Solver, string> = {
  ok: "text-running",
  building: "text-warn",
  overrun: "text-warn",
  error: "text-alarm",
  idle: "text-fg-muted",
};

/** Lâmpada do solver: cor + forma + rótulo (Regra do Canal Redundante). Vocabulário de forma
 *  por severidade — mesmo critério de `LampadaSeveridade` (`EventsPage.tsx`): círculo =
 *  informativo (ok/idle), triângulo = aviso (building/overrun), losango = alarme (error). */
function LampadaSolver({ solver }: { solver: Solver }) {
  return (
    <span
      data-testid="faceplate-lampada-solver"
      className={cn("inline-flex items-center gap-1.5", COR_SOLVER[solver])}
    >
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {(solver === "ok" || solver === "idle") && <circle cx="5" cy="5" r="4" />}
        {(solver === "building" || solver === "overrun") && <path d="M5 0 10 9H0L5 0Z" />}
        {solver === "error" && <path d="M5 0 10 5 5 10 0 5Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{ROTULO_SOLVER[solver]}</span>
    </span>
  );
}

/** Lâmpada do flow (`flow.status.state`): mesma convenção visual de `LampadaEstado`
 *  (`FlowEditorPage.tsx`) — círculo verde rodando, quadrado vazado parado, triângulo alarme
 *  falha — reaproveitando o rótulo já traduzido (`ROTULO_ESTADO`, `useFlowStatus.ts`). */
function LampadaFlow({ estado }: { estado: EstadoFlow }) {
  const cor = estado === "running" ? "text-running" : estado === "failed" ? "text-alarm" : "text-fg-muted";
  return (
    <span data-testid="faceplate-lampada-flow" className={cn("inline-flex items-center gap-1.5", cor)}>
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {estado === "running" && <circle cx="5" cy="5" r="4" />}
        {estado === "stopped" && <rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" />}
        {estado === "failed" && <path d="M5 0 10 9H0L5 0Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{ROTULO_ESTADO[estado]}</span>
    </span>
  );
}

/** Lâmpada `input_valid`: entradas do solver frescas/íntegras. Sem terceiro estado — booleano
 *  do wire (`MpcStatus.input_valid`) —, então só 2 posições (Regra do Canal Redundante). */
function LampadaInputValido({ valido }: { valido: boolean }) {
  return (
    <span
      data-testid="faceplate-lampada-input-valido"
      className={cn("inline-flex items-center gap-1.5", valido ? "text-running" : "text-warn")}
    >
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {valido ? <circle cx="5" cy="5" r="4" /> : <path d="M5 0 10 9H0L5 0Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{valido ? "Entradas válidas" : "Entradas inválidas"}</span>
    </span>
  );
}

/** Comutador de posição (DESIGN.md §Shapes): segmented control de posições nítidas, nunca
 *  toggle "amigável". `pendente` (não-nulo) pinta o segmento comandado em fantasma + outline
 *  azul até `mpc.state` confirmar (Regra do Estado Publicado). */
function Comutador<T extends string>({
  testid,
  posicoes,
  atual,
  pendente,
  desabilitado,
  motivoDesabilitado,
  onSelecionar,
}: {
  testid: string;
  posicoes: readonly { valor: T; rotulo: string }[];
  atual: T;
  pendente: T | null;
  desabilitado: boolean;
  motivoDesabilitado: string | null;
  onSelecionar: (valor: T) => void;
}) {
  const exibido = pendente ?? atual;
  return (
    <div data-testid={testid} className="inline-flex flex-col items-start gap-1">
      <div className="inline-flex overflow-hidden rounded-panel border border-hairline">
        {posicoes.map((posicao) => {
          const ativo = posicao.valor === exibido;
          const emFantasma = ativo && pendente !== null;
          return (
            <button
              key={posicao.valor}
              type="button"
              data-testid={`${testid}-${posicao.valor}`}
              disabled={desabilitado}
              aria-pressed={ativo}
              onClick={() => onSelecionar(posicao.valor)}
              className={cn(
                "plaqueta px-3 py-1.5 text-[11px] transition-colors",
                ativo ? "bg-accent text-field" : "bg-panel text-fg-muted hover:text-fg",
                emFantasma && "opacity-70 outline outline-2 -outline-offset-2 outline-accent",
                desabilitado && "cursor-not-allowed opacity-40",
              )}
            >
              {posicao.rotulo}
            </button>
          );
        })}
      </div>
      {desabilitado && motivoDesabilitado !== null && (
        <p className="text-[11px] text-warn">{motivoDesabilitado}</p>
      )}
    </div>
  );
}

const POSICOES_LOCAL_REMOTO = [
  { valor: "local" as const, rotulo: "LOCAL" },
  { valor: "remote" as const, rotulo: "REMOTO" },
];
const POSICOES_MAN_AUTO = [
  { valor: "man" as const, rotulo: "MAN" },
  { valor: "auto" as const, rotulo: "AUTO" },
];

const INTERVALO_TIQUE_MS = 1000;

export interface FaceplatePrincipalProps {
  mpc: MpcNodeOut;
  flowStatus: FlowStatus | undefined;
  mpcState: MpcState | undefined;
  flowId: number;
  blockId: string;
}

export function FaceplatePrincipal({ mpc, flowStatus, mpcState, flowId, blockId }: FaceplatePrincipalProps) {
  const [pendencia, dispatch] = useReducer(reduzirPendencia, null as Pendencia | null);
  const [erroComando, setErroComando] = useState<string | null>(null);
  const tsMpcSegundos = mpc.flow_ts_seconds * mpc.multiplier;

  // Materializa/mantém a pendência a cada `mpc.state` novo publicado pelo canal ao vivo.
  useEffect(() => {
    if (mpcState === undefined) return;
    dispatch({ tipo: "estadoPublicado", state: mpcState, agora: Date.now() });
  }, [mpcState]);

  // Relógio da expiração (janela 3×Ts_mpc, mín. 5s) — sem tique, uma pendência sem estado
  // publicado que a confirme nunca reverteria (F5R-18).
  useEffect(() => {
    const id = window.setInterval(() => dispatch({ tipo: "tique", agora: Date.now() }), INTERVALO_TIQUE_MS);
    return () => window.clearInterval(id);
  }, []);

  async function enviarModo(axis: "local_remote" | "man_auto", value: PosicaoLocalRemoto | PosicaoManAuto) {
    setErroComando(null);
    try {
      await api(`/api/operate/${String(flowId)}/${blockId}/mode`, {
        method: "POST",
        body: JSON.stringify({ axis, value }),
      });
      dispatch({
        tipo: "comandar",
        alvo: `modes.${axis}`,
        valor: value,
        tsMpcSegundos,
        agora: Date.now(),
      });
    } catch (motivo) {
      setErroComando(motivo instanceof ApiError ? motivo.message : "Falha ao enviar comando de modo");
    }
  }

  const semDados = mpcState === undefined;
  const building = mpcState?.status.solver === "building";
  const localRemotoAtual: PosicaoLocalRemoto = mpcState?.modes.local_remote ?? "local";
  const manAutoAtual: PosicaoManAuto = mpcState?.modes.man_auto ?? "man";
  const pendenteLocalRemoto =
    pendencia?.alvo === "modes.local_remote" ? (pendencia.valorComandado as PosicaoLocalRemoto) : null;
  const pendenteManAuto =
    pendencia?.alvo === "modes.man_auto" ? (pendencia.valorComandado as PosicaoManAuto) : null;
  // ADR-010: MAN/AUTO só renderiza em REMOTO — gate pelo estado publicado (confirmado), não
  // pelo fantasma, para o comutador não aparecer/sumir antes da confirmação real.
  const emRemoto = mpcState?.modes.local_remote === "remote";

  const motivoDesabilitado = semDados
    ? "Aguardando estado ao vivo do bloco…"
    : building
      ? "Solver em build — comutadores desabilitados até a partida concluir."
      : null;
  const modosDesabilitados = semDados || building;

  return (
    <Card className="p-6" data-testid="faceplate-principal">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="plaqueta text-xs text-fg-muted">{mpc.flow_name}</h2>
          <p className="mt-1 text-lg" data-testid="faceplate-plaqueta">
            {mpc.name} <span className="text-fg-muted">·</span> {mpc.flow_name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <LampadaFlow estado={flowStatus?.state ?? "stopped"} />
          <LampadaSolver solver={mpcState?.status.solver ?? "idle"} />
          <LampadaInputValido valido={mpcState?.status.input_valid ?? false} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-start gap-6">
        <Comutador
          testid="faceplate-modo-local-remoto"
          posicoes={POSICOES_LOCAL_REMOTO}
          atual={localRemotoAtual}
          pendente={pendenteLocalRemoto}
          desabilitado={modosDesabilitados}
          motivoDesabilitado={motivoDesabilitado}
          onSelecionar={(valor) => void enviarModo("local_remote", valor)}
        />
        {emRemoto && (
          <Comutador
            testid="faceplate-modo-man-auto"
            posicoes={POSICOES_MAN_AUTO}
            atual={manAutoAtual}
            pendente={pendenteManAuto}
            desabilitado={modosDesabilitados}
            motivoDesabilitado={motivoDesabilitado}
            onSelecionar={(valor) => void enviarModo("man_auto", valor)}
          />
        )}
      </div>

      {erroComando !== null && (
        <p role="alert" data-testid="faceplate-erro-comando" className="mt-3 text-sm text-alarm">
          {erroComando}
        </p>
      )}

      <p className="mt-4 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
        <span data-testid="faceplate-ts-mpc">
          Ts MPC{" "}
          <span className="process-value text-fg">{formatarNumero(mpc.horizons.ts_mpc)}</span> s
        </span>
        <span className="text-fg-muted">·</span>
        <span data-testid="faceplate-horizontes">
          Np <span className="process-value text-fg">{formatarNumero(mpc.horizons.np)}</span> (
          <span className="process-value text-fg">
            {formatarNumero((mpc.horizons.np * mpc.horizons.ts_mpc) / 60)}
          </span>{" "}
          min) · Nc{" "}
          <span className="process-value text-fg">{formatarNumero(mpc.horizons.nc)}</span>
        </span>
        <RelogioAgora />
      </p>

      <div className="mt-4 flex flex-wrap gap-6 text-sm text-fg-muted">
        <span>
          Overruns{" "}
          <span className="process-value text-fg" data-testid="faceplate-overruns">
            {mpcState !== undefined ? formatarNumero(mpcState.status.overruns) : "—"}
          </span>{" "}
          contagem
        </span>
        <span>
          Última solução{" "}
          <span className="process-value text-fg" data-testid="faceplate-last-solve-ms">
            {mpcState !== undefined ? formatarNumero(mpcState.status.last_solve_ms) : "—"}
          </span>{" "}
          ms
        </span>
      </div>
    </Card>
  );
}
