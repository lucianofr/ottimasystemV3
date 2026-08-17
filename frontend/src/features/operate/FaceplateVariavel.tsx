import { useEffect, useState } from "react";

import { Badge } from "../../components/ui/badge";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { api, ApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useCanalAoVivo } from "../../app/CanalAoVivo";
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
    /** Descrição curta (≤14) sob o nome — RF-610; vazia não renderiza nada. */
    description?: string;
    /** Faixa de instrumento (RF-609): a escala da barra é `[zero, zero+span]`. */
    zero?: number;
    span?: number;
    limits?: Faixa | null;
    sp_limits?: Faixa | null;
    range?: { low: number; high: number } | null;
    max_rate?: number | null;
    /** Tag OPC do PV ao vivo (canal `opc.values`, taxa OPC); `null`/ausente = fallback ao
     *  `mpc.state` (taxa do MPC). */
    tag_id?: number | null;
    /** CV com SP remoto (RF-614): o campo de SP fica desabilitado (escrita manual é 422). */
    remote_sp?: boolean;
    /** Rank do SSTO (ADR-027 §5; só CV/Restrição — MV/DV nunca têm) — maior = mais
     *  importante; vira o marcador numérico de prioridade no canto do faceplate. */
    priority?: number;
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

/** Faixa da escala da BARRA: a faixa de instrumento `[zero, zero+span]` (RF-609), para os 4
 *  tipos. Os limites de engenharia (`limits`/`sp_limits`/`range`) seguem na definição e
 *  continuam sendo o clamp dos COMANDOS (`enviar`) — mas a escala desenhada é a do
 *  instrumento. Defaults 0/100 reproduzem a faixa antiga quando zero/span não vieram na
 *  projeção (testes de unidade e projeções velhas). */
export function faixaDaEscala(props: FaceplateVariavelProps): Faixa | null {
  const zero = props.definicao.zero ?? 0;
  const span = props.definicao.span ?? 100;
  if (!Number.isFinite(zero) || !Number.isFinite(span) || span <= 0) return null;
  return { min: zero, max: zero + span };
}

/** Faixa de limite operacional (comando) por tipo — a MESMA fonte do clamp de `enviar()`
 *  (RF-704): `limits` (MV), `sp_limits` (CV), `range` (Restrição). NÃO é a escala da barra
 *  (essa é `faixaDaEscala`, RF-609) — vira os triângulos marcadores desenhados sobre ela. DV
 *  nunca é comandada: sem limite operacional, sem marcador. */
export function limiteOperacional(props: FaceplateVariavelProps): Faixa | null {
  const { tipo, definicao } = props;
  if (tipo === "mv") return definicao.limits ?? null;
  if (tipo === "cv") return definicao.sp_limits ?? null;
  if (tipo === "constraint") {
    return definicao.range != null
      ? { min: definicao.range.low, max: definicao.range.high }
      : null;
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

/** Triângulo marcador de limite operacional: ponta encostada na borda da barra, na altura
 *  do limite (`percentual`, mesma escala 0-100 de `percentualNaBarra`) — cor neutra (A Regra
 *  da Cor Anormal: limite configurado não é estado anormal, é dado estático). */
function MarcadorLimite({ percentual, testId }: { percentual: number; testId: string }) {
  return (
    <svg
      aria-hidden="true"
      width="6"
      height="8"
      viewBox="0 0 6 8"
      className="absolute text-fg-muted"
      style={{ left: "-6px", bottom: `${String(percentual)}%`, transform: "translateY(50%)" }}
      data-testid={testId}
    >
      <polygon points="0,0 0,8 6,4" fill="currentColor" />
    </svg>
  );
}

function BarraVertical({
  faixa,
  pv,
  sp,
  limite,
  testId,
}: {
  faixa: Faixa;
  pv: number | undefined;
  sp: number | null | undefined;
  limite: Faixa | null;
  testId: string;
}) {
  const pvPercentual = pv !== undefined ? percentualNaBarra(pv, faixa) : null;
  const spPercentual = sp !== null && sp !== undefined ? percentualNaBarra(sp, faixa) : null;
  const limiteMinPercentual = limite !== null ? percentualNaBarra(limite.min, faixa) : null;
  const limiteMaxPercentual = limite !== null ? percentualNaBarra(limite.max, faixa) : null;
  return (
    <div className="flex flex-col items-center gap-1">
      <span
        className="process-value text-[10px] text-fg-muted"
        data-testid={`${testId}-topo`}
      >
        {faixa.max.toFixed(2)}
      </span>
      <div className="relative h-32 w-4">
        <div
          className="absolute inset-0 overflow-hidden rounded-pill border border-border bg-well"
          data-testid={testId}
        >
          {pvPercentual !== null && (
            <div
              className="absolute inset-x-0 bottom-0 bg-[image:var(--gradient-accent)] opacity-25"
              style={{ height: `${String(pvPercentual)}%` }}
            />
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
        {limiteMinPercentual !== null && (
          <MarcadorLimite percentual={limiteMinPercentual} testId={`${testId}-limite-min`} />
        )}
        {limiteMaxPercentual !== null && (
          <MarcadorLimite percentual={limiteMaxPercentual} testId={`${testId}-limite-max`} />
        )}
      </div>
      <span
        className="process-value text-[10px] text-fg-muted"
        data-testid={`${testId}-base`}
      >
        {faixa.min.toFixed(2)}
      </span>
    </div>
  );
}

export default function FaceplateVariavel(props: FaceplateVariavelProps) {
  const { tipo, definicao, valor, modos, flowId, blockId, tsMpcSegundos } = props;
  const faixa = faixaDaEscala(props);
  const campoComandado = tipo === "mv" ? "v" : "sp";
  const alvo = `vars.${definicao.id}.${campoComandado}`;

  // PV na taxa OPC (decisão F6 A-1 revertida): variável com `tag_id` lê o valor ao vivo do
  // buffer `opc.values` (flush de 250 ms no provider); tag ausente ou leitura ruim cai no
  // `mpc.state` (comportamento anterior), sem erro — a barra e o PV grande usam `pv` abaixo.
  const canal = useCanalAoVivo();
  const leituraOpc = definicao.tag_id != null ? canal.tagValues.get(definicao.tag_id) : undefined;
  const pvOpc = leituraOpc !== undefined && leituraOpc.ok ? leituraOpc.v : undefined;
  const pv = pvOpc ?? valor?.v;

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
  // do shape de `MpcState` nunca é acessado. `state` do redutor é `unknown` (§6.6-3), então
  // este recorte parcial não precisa mais fingir ser um `MpcState` completo.
  useEffect(() => {
    if (valor === undefined) return;
    const estadoMinimo = { vars: { [definicao.id]: valor } };
    setPendencia((atual) =>
      reduzirPendencia(atual, { tipo: "estadoPublicado", state: estadoMinimo, agora: Date.now() }),
    );
  }, [valor, definicao.id]);

  const pendenciaAtiva = pendencia !== null && pendencia.alvo === alvo ? pendencia : null;

  const editavel =
    tipo === "mv"
      ? modos.local_remote === "remote" && modos.man_auto === "man"
      : tipo === "cv"
        ? // SP remoto (RF-614): a escrita manual é 422 — o campo já nasce desabilitado.
          modos.man_auto === "auto" && definicao.remote_sp !== true
        : false;

  async function enviar(): Promise<void> {
    if (!editavel || rascunho === null) return;
    // Clamp do comando: limites de engenharia (`limits`/`sp_limits`) — NÃO a escala do
    // instrumento: o operador comanda o curso inteiro do atuador mesmo com a barra
    // mostrando só a faixa de medição (RF-609).
    const faixaComando = tipo === "mv" ? definicao.limits : definicao.sp_limits;
    if (faixaComando == null) return;
    const bruto = Number(rascunho.replace(",", "."));
    if (!Number.isFinite(bruto)) {
      setErro("Valor inválido");
      return;
    }
    const alvoValor = clampNaFaixa(bruto, faixaComando);
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
      ? pv !== undefined && pv !== null
        ? pv.toFixed(2)
        : ""
      : valor?.sp != null
        ? valor.sp.toFixed(2)
        : "";
  const valorInput = rascunho ?? (pendenciaAtiva !== null ? String(pendenciaAtiva.valorComandado) : valorPublicadoTexto);

  return (
    <Card
      className="relative flex w-44 shrink-0 flex-col gap-3 p-4 transition-shadow duration-[var(--duration-fast)] hover:shadow-md"
      data-testid={`faceplate-${tipo}-${definicao.id}`}
      data-var-id={definicao.id}
      data-pendente={pendenciaAtiva !== null ? "true" : "false"}
    >
      {definicao.priority !== undefined && (
        <Badge
          tone="neutral"
          className="absolute right-2 top-2 px-1.5 py-0 text-[10px] leading-4"
          title={`Prioridade no otimizador (SSTO): ${String(definicao.priority)}`}
          data-testid={`faceplate-prioridade-${definicao.id}`}
        >
          {definicao.priority}
        </Badge>
      )}
      <div>
        <Label className="block">{ROTULO_TIPO[tipo]}</Label>
        <p className="truncate text-sm text-fg" title={definicao.name}>
          {definicao.name}
        </p>
        {(definicao.description ?? "") !== "" && (
          <p
            className="truncate text-[10px] text-fg-muted"
            data-testid={`faceplate-desc-${definicao.id}`}
          >
            {definicao.description}
          </p>
        )}
      </div>

      <div className="flex items-end justify-center gap-3">
        {faixa !== null && (
          <BarraVertical
            faixa={faixa}
            limite={limiteOperacional(props)}
            pv={pv}
            sp={tipo === "cv" ? (valor?.sp ?? null) : null}
            testId={`faceplate-escala-${definicao.id}`}
          />
        )}
        <div className="text-right">
          <p
            className="process-value text-3xl font-medium leading-none tracking-tight"
            data-testid={`faceplate-pv-${definicao.id}`}
          >
            {pv !== undefined && pv !== null ? pv.toFixed(2) : "—"}
          </p>
          <p className="plaqueta mt-1 text-[10px]">{definicao.eu}</p>
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
        <p
          role="alert"
          data-testid={`faceplate-erro-${definicao.id}`}
          className="rounded-sm bg-alarm-soft px-2 py-1 text-xs text-alarm"
        >
          {erro}
        </p>
      )}
    </Card>
  );
}
