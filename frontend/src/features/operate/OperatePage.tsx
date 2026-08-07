import { Navigate, useParams } from "react-router";

import { Card } from "../../components/ui/card";
import { useAssinatura } from "../../app/CanalAoVivo";
import { useMpcs } from "./useMpcs";

/**
 * Casca real da tela de operação (spec §7.4-1/2; RF-701): plaqueta do bloco MPC aberto
 * (nome do bloco · flow), assinatura no canal ao vivo (`mpc_state` do bloco + `flow_status`
 * do flow, via `useAssinatura`) e os estados de carregando/erro/ausente da descoberta
 * (`GET /api/operate/mpcs`, revalidada ao montar/focar pelo default do react-query).
 *
 * Faceplates e trend com predição (conteúdo do MPC em si) chegam nas tarefas 4.3-5.3 — nada
 * aqui simula valor de bloco.
 */
function OperacaoDoMpc({ flowId, blockId }: { flowId: number; blockId: string }) {
  const mpcs = useMpcs();
  useAssinatura({ flow_status: [flowId], mpc_state: [`${String(flowId)}/${blockId}`] });

  if (mpcs.isPending) {
    return (
      <Card className="max-w-lg p-6" data-testid="operate-carregando">
        <p className="text-sm text-fg-muted">Carregando…</p>
      </Card>
    );
  }

  if (mpcs.isError) {
    return (
      <Card className="max-w-lg p-6">
        <p role="alert" data-testid="operate-erro" className="text-sm text-alarm">
          Falha ao consultar blocos MPC
        </p>
      </Card>
    );
  }

  // MPC ausente na revalidação (flow excluído / projeto trocado, §7.4-2): volta ao seletor
  // com aviso — nunca fica preso numa tela de operação sem bloco nenhum atrás dela.
  const mpc = mpcs.data.find((m) => m.flow_id === flowId && m.block_id === blockId);
  if (mpc === undefined) {
    return (
      <Navigate
        to="/operacao"
        replace
        state={{ aviso: "O bloco MPC solicitado não está mais disponível." }}
      />
    );
  }

  return (
    <Card className="max-w-lg p-6" data-testid="operate-page">
      <h2 className="plaqueta text-xs text-fg-muted">{mpc.flow_name}</h2>
      <p className="mt-2 text-lg" data-testid="operate-mpc-nome">
        {mpc.name}
      </p>
    </Card>
  );
}

/**
 * Um MPC por rota aberta (`/operacao/:flowId/:blockId`) — o MPC aberto vive na URL (F5 do
 * browser restaura a tela, "sala de controle"). `key` força remonte ao trocar de MPC sem
 * passar pelo seletor: mesmo padrão de `FlowEditorPage.tsx` (`<Editor key={id} .../>`), já
 * que `useAssinatura` só lê o interesse do primeiro render do componente.
 */
export function OperatePage() {
  const { flowId, blockId } = useParams();
  const id = Number(flowId);
  if (!Number.isInteger(id) || id < 1 || !blockId) {
    return <Navigate to="/operacao" replace state={{ aviso: "MPC inválido na URL." }} />;
  }
  return <OperacaoDoMpc key={`${String(id)}/${blockId}`} flowId={id} blockId={blockId} />;
}
