import { Link, Navigate, useLocation } from "react-router";

import { Card } from "../../components/ui/card";
import { useMpcs, type MpcNodeOut } from "./useMpcs";

/** `nome do flow · nome do bloco` — mesma composição de rótulo do atalho da Home
 *  (`HomePage.tsx::LinhaFlow`, "Operar <nome>"), só que aqui o flow também precisa aparecer:
 *  o seletor lista MPCs de flows diferentes lado a lado. */
function rotuloMpc(mpc: MpcNodeOut): string {
  return `${mpc.flow_name} · ${mpc.name}`;
}

/**
 * Seletor e roteamento da operação (spec F5 §7.4-1/2; RF-701; decisão A-7): `/operacao` sem
 * parâmetro lista via `GET /api/operate/mpcs` (`useMpcs`, compartilhado com a Home — tarefa
 * 3.2); **um único MPC no projeto ativo redireciona direto** pra `OperatePage`, sem tela
 * intermediária.
 *
 * Também é o destino do "volta ao seletor com aviso" (§7.4-2): quando a `OperatePage` perde
 * o MPC aberto numa revalidação (flow excluído / projeto trocado), ela navega pra cá com
 * `state.aviso` — lido aqui, nunca uma tela de aviso à parte.
 */
export function OperateSelectorPage() {
  const mpcs = useMpcs();
  const aviso = (useLocation().state as { aviso?: string } | null)?.aviso ?? null;

  if (mpcs.isSuccess && mpcs.data.length === 1) {
    const unico = mpcs.data[0];
    return <Navigate to={`/operacao/${String(unico.flow_id)}/${unico.block_id}`} replace />;
  }

  return (
    <Card className="max-w-lg p-6" data-testid="operate-selector">
      <h2 className="plaqueta text-xs text-fg-muted">Operação</h2>
      {aviso !== null && (
        <p role="status" data-testid="operate-selector-aviso" className="mt-2 text-sm text-warn">
          {aviso}
        </p>
      )}
      {mpcs.isPending && <p className="mt-2 text-sm text-fg-muted">Carregando…</p>}
      {mpcs.isError && (
        <p role="alert" data-testid="operate-selector-error" className="mt-2 text-sm text-alarm">
          Falha ao consultar blocos MPC
        </p>
      )}
      {mpcs.isSuccess && mpcs.data.length === 0 && (
        <p data-testid="operate-selector-empty" className="mt-2 text-sm text-fg-muted">
          Nenhum bloco MPC configurado no projeto ativo.
        </p>
      )}
      {mpcs.isSuccess && mpcs.data.length > 1 && (
        <ul className="mt-2 divide-y divide-hairline" data-testid="operate-selector-lista">
          {mpcs.data.map((mpc) => (
            <li key={`${String(mpc.flow_id)}/${mpc.block_id}`} className="py-2">
              <Link
                to={`/operacao/${String(mpc.flow_id)}/${mpc.block_id}`}
                data-testid="operate-mpc-link"
                data-flow-id={mpc.flow_id}
                data-block-id={mpc.block_id}
                className="text-sm text-accent hover:underline"
              >
                {rotuloMpc(mpc)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
