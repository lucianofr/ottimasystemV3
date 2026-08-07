import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useCanalAoVivo } from "../../app/CanalAoVivo";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { cn } from "../../lib/cn";
import { api, type EventOut } from "../../lib/api";
import { useActiveProject, useConnections } from "../connections/useConnections";
import { useFlows } from "../flows/useFlows";
import {
  calcularEventosVisiveis,
  chaveEvento,
  origensConhecidas,
  type FiltrosEventos,
  type MpcNodeOut,
} from "./eventos";

/** Teto da consulta histórica (spec §7.5, `routers/events.py:DEFAULT_LIMIT=100`,
 *  `MAX_LIMIT=1000`): mesmo teto de memória do buffer ao vivo (`TETO_EVENTOS`,
 *  `CanalAoVivo.tsx`) — não há motivo pra a REST trazer menos histórico que o socket guarda. */
const LIMITE_HISTORICO = 200;

const ROTULO_SEVERIDADE: Record<EventOut["severity"], string> = {
  info: "Informação",
  warning: "Aviso",
  alarm: "Alarme",
};

const COR_SEVERIDADE: Record<EventOut["severity"], string> = {
  info: "text-fg-muted",
  warning: "text-warn",
  alarm: "text-alarm",
};

/** Lâmpada de severidade: forma + cor + rótulo textual (Regra do Canal Redundante,
 *  DESIGN.md §Colors) — mesma convenção de `LampadaEstado` (`FlowEditorPage.tsx`), com
 *  vocabulário de forma próprio porque o domínio (severidade de evento, não estado de
 *  flow) é outro: círculo = informativo, triângulo = aviso, losango = alarme. */
function LampadaSeveridade({ severidade }: { severidade: EventOut["severity"] }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", COR_SEVERIDADE[severidade])}>
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        {severidade === "info" && <circle cx="5" cy="5" r="4" />}
        {severidade === "warning" && <path d="M5 0 10 9H0L5 0Z" />}
        {severidade === "alarm" && <path d="M5 0 10 5 5 10 0 5Z" />}
      </svg>
      <span className="plaqueta text-[11px]">{ROTULO_SEVERIDADE[severidade]}</span>
    </span>
  );
}

const COLUNAS = ["Ts", "Severidade", "Origem", "Mensagem", "Payload"] as const;

/** Página `/eventos` (spec F5 §7.5; decisão A-13; RF-803; F5R-24; tarefa 3.3). Tabela ts
 *  desc com filtros combináveis (severidade/origem/período, `GET /api/events` — a API
 *  filtra por igualdade exata, então origem é sempre `<select>`, nunca texto livre).
 *  Sem filtro de período: eventos novos do canal ao vivo que casem os filtros entram no
 *  topo com marca de recém-chegado (`eventos.ts::calcularEventosVisiveis`); com período,
 *  consulta histórica pura. */
export function EventsPage() {
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;
  const flows = useFlows(projectId);
  const conexoes = useConnections(projectId);
  const mpcs = useQuery({
    queryKey: ["operate", "mpcs"],
    queryFn: () => api<MpcNodeOut[]>("/api/operate/mpcs"),
  });

  const [severidade, setSeveridade] = useState("");
  const [origem, setOrigem] = useState("");
  const [inicio, setInicio] = useState("");
  const [fim, setFim] = useState("");

  const filtros: FiltrosEventos = {
    severity: severidade === "" ? null : (severidade as EventOut["severity"]),
    origin: origem === "" ? null : origem,
    start: inicio === "" ? null : inicio,
    end: fim === "" ? null : fim,
  };

  const historico = useQuery({
    queryKey: ["events", filtros],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filtros.severity !== null) params.set("severity", filtros.severity);
      if (filtros.origin !== null) params.set("origin", filtros.origin);
      if (filtros.start !== null) params.set("start", filtros.start);
      if (filtros.end !== null) params.set("end", filtros.end);
      params.set("limit", String(LIMITE_HISTORICO));
      return api<EventOut[]>(`/api/events?${params.toString()}`);
    },
  });

  // `events` sempre assinado pelo provider (spec §7.1-3) — sem `useAssinatura` aqui.
  const aoVivo = useCanalAoVivo().eventos;
  const linhasHistorico = historico.data ?? [];
  const visiveis = useMemo(
    () => calcularEventosVisiveis(linhasHistorico, aoVivo, filtros),
    [linhasHistorico, aoVivo, severidade, origem, inicio, fim],
  );
  const opcoesOrigem = useMemo(
    () => origensConhecidas(flows.data ?? [], mpcs.data ?? [], conexoes.data ?? [], linhasHistorico),
    [flows.data, mpcs.data, conexoes.data, linhasHistorico],
  );

  return (
    <section className="space-y-4">
      <h1 className="plaqueta text-sm">Eventos</h1>

      <Card className="grid gap-3 p-4 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="eventos-filtro-severidade">Severidade</Label>
          <Select
            id="eventos-filtro-severidade"
            data-testid="eventos-filtro-severidade"
            value={severidade}
            onChange={(e) => setSeveridade(e.target.value)}
          >
            <option value="">Todas</option>
            <option value="info">Informação</option>
            <option value="warning">Aviso</option>
            <option value="alarm">Alarme</option>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="eventos-filtro-origem">Origem</Label>
          <Select
            id="eventos-filtro-origem"
            data-testid="eventos-filtro-origem"
            value={origem}
            onChange={(e) => setOrigem(e.target.value)}
          >
            <option value="">Todas</option>
            {opcoesOrigem.map((opcao) => (
              <option key={opcao.value} value={opcao.value}>
                {opcao.rotulo}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="eventos-filtro-inicio">Início do período</Label>
          <Input
            id="eventos-filtro-inicio"
            data-testid="eventos-filtro-inicio"
            type="datetime-local"
            value={inicio}
            onChange={(e) => setInicio(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="eventos-filtro-fim">Fim do período</Label>
          <Input
            id="eventos-filtro-fim"
            data-testid="eventos-filtro-fim"
            type="datetime-local"
            value={fim}
            onChange={(e) => setFim(e.target.value)}
          />
        </div>
      </Card>

      <Card className="overflow-hidden">
        <table className="w-full border-collapse text-sm" data-testid="eventos-tabela">
          <thead>
            <tr className="border-b border-hairline">
              {COLUNAS.map((coluna) => (
                <th key={coluna} className="plaqueta px-3 py-2 text-left text-xs text-fg-muted">
                  {coluna}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {historico.isPending && (
              <tr>
                <td colSpan={COLUNAS.length} className="px-3 py-4 text-fg-muted">
                  Carregando…
                </td>
              </tr>
            )}
            {historico.isError && (
              <tr>
                <td colSpan={COLUNAS.length} className="px-3 py-4 text-alarm" role="alert">
                  Falha ao consultar eventos
                </td>
              </tr>
            )}
            {historico.isSuccess && visiveis.eventos.length === 0 && (
              <tr>
                <td colSpan={COLUNAS.length} className="px-3 py-4 text-fg-muted">
                  Nenhum evento encontrado
                </td>
              </tr>
            )}
            {visiveis.eventos.map((evento) => {
              const chave = chaveEvento(evento);
              return (
                <tr key={chave} data-testid="eventos-linha" className="border-b border-hairline align-top">
                  <td className="process-value px-3 py-2 text-xs text-fg-muted">
                    {new Date(evento.ts).toLocaleString("pt-BR")}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <LampadaSeveridade severidade={evento.severity} />
                      {visiveis.recentes.has(chave) && (
                        <span
                          data-testid="eventos-novo"
                          className="plaqueta rounded-panel border border-accent px-1.5 py-0.5 text-[10px] text-accent"
                        >
                          Novo
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs">{evento.origin}</td>
                  <td className="px-3 py-2">{evento.message}</td>
                  <td className="px-3 py-2">
                    <details>
                      <summary className="cursor-pointer text-xs text-fg-muted">Payload</summary>
                      <pre className="mt-1 max-w-md overflow-x-auto text-[11px] text-fg-muted">
                        {JSON.stringify(evento.payload, null, 2)}
                      </pre>
                    </details>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </section>
  );
}
