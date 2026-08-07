import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Card } from "../components/ui/card";
import { useActiveProject } from "../features/connections/useConnections";
import { useFlows } from "../features/flows/useFlows";
import { useLastFlowState, type UltimoEstadoFlow } from "../features/flows/useLastFlowState";
import { api } from "../lib/api";
import type { components } from "../lib/api-types";
import { derivarLampadas, useWorkersHealth, type LampadaWorker } from "./useWorkersHealth";

/** `MpcNodeOut` já é gerado em `lib/api-types.ts` a partir de `/api/operate/mpcs`, mas
 *  `lib/api.ts` (onde o resto do app importa tipos de API) é infraestrutura compartilhada fora
 *  do escopo desta tarefa — a tarefa 3.3 do mesmo plano também consome `/api/operate/mpcs` em
 *  paralelo. Import direto do gerado evita as duas tarefas colidirem no mesmo arquivo. */
type MpcNodeOut = components["schemas"]["MpcNodeOut"];

/** Agrupa os blocos MPC projetados por flow — um flow pode ter mais de um bloco `mpc`
 *  (plano F5b tarefa 3.2: "atalho por flow para a operação quando houver MPC"). */
export function agruparMpcsPorFlow(mpcs: readonly MpcNodeOut[]): ReadonlyMap<number, MpcNodeOut[]> {
  const porFlow = new Map<number, MpcNodeOut[]>();
  for (const mpc of mpcs) {
    const atuais = porFlow.get(mpc.flow_id);
    if (atuais) atuais.push(mpc);
    else porFlow.set(mpc.flow_id, [mpc]);
  }
  return porFlow;
}

function IconeLampada({ ativo }: { ativo: boolean }) {
  if (ativo) {
    return (
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
        <path d="M6.5 11.4 2.6 7.5l1.4-1.4 2.5 2.5L11.9 3.2l1.4 1.4-6.8 6.8Z" />
      </svg>
    );
  }
  // Mesmo triângulo de alerta do resto do app (AnnunciatorBar/ConnectionsPage/FlowsPage).
  return (
    <svg aria-hidden="true" width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
      <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
    </svg>
  );
}

/** Lâmpada de estado (DESIGN.md §Shapes): quadrado com ícone + rótulo, nunca só cor — o verde
 *  "rodando" e o vermelho "alarme" ficam restritos ao quadrado pequeno (§Colors, Regra da Cor
 *  Anormal), o texto ao lado nunca herda a cor de severidade. */
function Lampada({ lampada }: { lampada: LampadaWorker }) {
  return (
    <div data-testid="home-worker-lamp" data-worker={lampada.id} className="flex items-center gap-2">
      <span
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-field ${
          lampada.ativo ? "bg-running" : "bg-alarm"
        }`}
      >
        <IconeLampada ativo={lampada.ativo} />
      </span>
      <span className="text-sm">
        <span className="plaqueta block text-[10px] text-fg-muted">{lampada.rotulo}</span>
        {lampada.estado}
      </span>
    </div>
  );
}

/** Mesmo padrão de `FlowsPage.tsx`/`ConnectionsPage.tsx`: sem estado publicado ainda é "—";
 *  falha ganha cor + ícone + texto (Regra do Canal Redundante), estado normal é só texto. */
function CelulaUltimoEstado({ estado }: { estado: UltimoEstadoFlow | undefined }) {
  if (!estado) {
    return (
      <span data-testid="home-flow-last-state" className="text-fg-muted">
        —
      </span>
    );
  }
  if (!estado.falha) {
    return <span data-testid="home-flow-last-state">{estado.rotulo}</span>;
  }
  return (
    <span data-testid="home-flow-last-state" className="flex items-center gap-1.5 text-alarm">
      <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
        <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
      </svg>
      {estado.rotulo}
    </span>
  );
}

function LinhaFlow({
  flowId,
  nome,
  estado,
  mpcs,
}: {
  flowId: number;
  nome: string;
  estado: UltimoEstadoFlow | undefined;
  mpcs: readonly MpcNodeOut[];
}) {
  return (
    <li
      data-testid="home-flow-row"
      data-flow-id={flowId}
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-1.5"
    >
      <div className="flex items-center gap-3">
        <span className="text-sm">{nome}</span>
        <CelulaUltimoEstado estado={estado} />
      </div>
      {mpcs.length > 0 && (
        <div className="flex items-center gap-3">
          {mpcs.map((mpc) => (
            <Link
              key={mpc.block_id}
              to={`/operacao/${String(flowId)}/${mpc.block_id}`}
              data-testid="home-flow-operate-link"
              className="plaqueta text-[10px] text-accent hover:underline"
            >
              Operar {mpc.name}
            </Link>
          ))}
        </div>
      )}
    </li>
  );
}

/** Home = visão geral do console (spec F5 §7.3-3; DESIGN §Layout; decisão A-10; RNF-07):
 *  lâmpadas dos 3 workers, flows do projeto ativo com "Último estado" (padrão F3 §6.1) e
 *  atalho de operação nos flows com bloco MPC. */
export function HomePage() {
  const projeto = useActiveProject();
  const projectId = projeto.data?.id ?? null;

  const flows = useFlows(projectId);
  const linhas = flows.data ?? [];
  const estados = useLastFlowState(linhas.map((flow) => flow.id));

  const mpcs = useQuery({
    queryKey: ["operate", "mpcs"],
    queryFn: () => api<MpcNodeOut[]>("/api/operate/mpcs"),
  });
  const mpcsPorFlow = agruparMpcsPorFlow(mpcs.data ?? []);

  const workers = useWorkersHealth();
  const lampadas = derivarLampadas(workers.data);

  return (
    <section className="space-y-4">
      <Card className="max-w-lg p-6">
        <h2 className="plaqueta text-xs text-fg-muted">Projeto ativo</h2>
        {projeto.isPending && <p className="mt-2 text-sm text-fg-muted">Carregando…</p>}
        {projeto.isError && (
          <p role="alert" className="mt-2 text-sm text-alarm">
            Falha ao consultar projetos
          </p>
        )}
        {!projeto.isPending && !projeto.isError && (
          <p data-testid="active-project" className="mt-2 text-lg">
            {projeto.data ? projeto.data.name : "Nenhum projeto ativo"}
          </p>
        )}
      </Card>

      <Card className="p-6" data-testid="home-workers">
        <h2 className="plaqueta text-xs text-fg-muted">Workers</h2>
        {workers.isError && (
          <p role="alert" data-testid="home-workers-error" className="mt-2 text-sm text-alarm">
            Falha ao consultar saúde dos workers
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-6">
          {lampadas.map((lampada) => (
            <Lampada key={lampada.id} lampada={lampada} />
          ))}
        </div>
      </Card>

      <Card className="p-6" data-testid="home-flows">
        <h2 className="plaqueta text-xs text-fg-muted">Flows do projeto ativo</h2>
        {mpcs.isError && (
          <p role="alert" data-testid="home-mpcs-error" className="mt-2 text-sm text-alarm">
            Falha ao consultar blocos MPC
          </p>
        )}
        {projeto.isSuccess && projectId === null && (
          <p className="mt-2 text-sm text-fg-muted">Nenhum projeto ativo.</p>
        )}
        {flows.isPending && projectId !== null && (
          <p className="mt-2 text-sm text-fg-muted">Carregando…</p>
        )}
        {flows.isError && (
          <p role="alert" className="mt-2 text-sm text-alarm">
            Falha ao consultar flows
          </p>
        )}
        {flows.isSuccess && linhas.length === 0 && (
          <p className="mt-2 text-sm text-fg-muted">Nenhum flow cadastrado.</p>
        )}
        {linhas.length > 0 && (
          <ul className="mt-2 divide-y divide-hairline">
            {linhas.map((flow) => (
              <LinhaFlow
                key={flow.id}
                flowId={flow.id}
                nome={flow.name}
                estado={estados.get(flow.id)}
                mpcs={mpcsPorFlow.get(flow.id) ?? []}
              />
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}
