import { Navigate, useNavigate, useParams } from "react-router";

import { useAssinatura, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { FaceplatePrincipal } from "./FaceplatePrincipal";
import FaceplateVariavel from "./FaceplateVariavel";
import { gradeDeVariaveis } from "./gradeVariaveis";
import { ResumoOtimizador } from "./ResumoOtimizador";
import { TrendOperacao } from "./TrendOperacao";
import { rotuloMpc, useMpcs, type MpcNodeOut } from "./useMpcs";

/**
 * Casca real da tela de operação (spec §7.4-1/2/3/5; RF-701/702): resolve o MPC de
 * `useMpcs`, assina o canal ao vivo (`mpc_state` do bloco + `flow_status` do flow, via
 * `useAssinatura`) e trata os estados de carregando/erro/ausente da descoberta
 * (`GET /api/operate/mpcs`, revalidada ao montar/focar pelo default do react-query). A
 * plaqueta `nome · flow` mora dentro do faceplate principal (tarefa 4.3); a fileira de
 * faceplates de variável (tarefa 4.4) monta na ordem MV → CV → Restrição → DV (§7.4-5);
 * o trend central com predição (Etapa 5) monta abaixo da fileira de faceplates.
 */


/** Conteúdo da operação com o MPC já resolvido: só monta com `mpcs.data` em mãos — a
 *  assinatura (que só lê o interesse do primeiro render, ver `OperatePage`) já nasce com as
 *  tags `opc_values` das variáveis com tag mapeada (PV na taxa OPC, decisão F6 A-1
 *  revertida). Variável sem `tag_id` (CV alimentada por filtro/script) segue só no
 *  `mpc.state` — fallback explícito, sem erro. */
function OperacaoResolvida({
  mpc,
  indiceAtual,
  mpcs,
}: {
  mpc: MpcNodeOut;
  indiceAtual: number;
  mpcs: MpcNodeOut[];
}) {
  const navigate = useNavigate();
  const flowId = mpc.flow_id;
  const blockId = mpc.block_id;
  const tagIds = [
    ...new Set(
      [
        ...mpc.variables.mvs,
        ...mpc.variables.cvs,
        ...mpc.variables.constraints,
        ...mpc.variables.dvs,
      ]
        .map((v) => v.tag_id)
        .filter((id): id is number => id != null),
    ),
  ];
  useAssinatura({
    flow_status: [flowId],
    mpc_state: [`${String(flowId)}/${blockId}`],
    opc_values: tagIds,
  });
  const canal = useCanalAoVivo();
  const mpcState = canal.mpcStates.get(`${String(flowId)}/${blockId}`);

  return (
    <div data-testid="operate-page">
      <label className="mb-4 flex items-center gap-2">
        <span className="plaqueta text-xs text-fg-muted">MPC</span>
        <Select
          data-testid="operate-mpc-select"
          className="w-72"
          value={String(indiceAtual)}
          onChange={(evento) => {
            const escolhido = mpcs[Number(evento.target.value)];
            navigate(`/operacao/${String(escolhido.flow_id)}/${escolhido.block_id}`);
          }}
        >
          {mpcs.map((item, indice) => (
            <option key={`${String(item.flow_id)}/${item.block_id}`} value={indice}>
              {rotuloMpc(item)}
            </option>
          ))}
        </Select>
      </label>
      <FaceplatePrincipal
        mpc={mpc}
        flowStatus={canal.flowStatus.get(flowId)}
        mpcState={mpcState}
        flowId={flowId}
        blockId={blockId}
      />
      <div className="mt-6">
        <ResumoOtimizador mpc={mpc} mpcState={mpcState} flowId={flowId} blockId={blockId} />
      </div>
      <div data-testid="operate-variaveis" className="mt-6 flex flex-wrap gap-4">
        {gradeDeVariaveis(mpc, mpcState, flowId, blockId).map(({ key, ...props }) => (
          <FaceplateVariavel key={key} {...props} />
        ))}
      </div>
      <div className="mt-6">
        <TrendOperacao flowId={flowId} blockId={blockId} mpc={mpc} mpcState={mpcState} />
      </div>
    </div>
  );
}


function OperacaoDoMpc({ flowId, blockId }: { flowId: number; blockId: string }) {
  const mpcs = useMpcs();

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
  const indiceAtual = mpcs.data.findIndex((m) => m.flow_id === flowId && m.block_id === blockId);
  if (mpc === undefined) {
    return (
      <Navigate
        to="/operacao"
        replace
        state={{ aviso: "O bloco MPC solicitado não está mais disponível." }}
      />
    );
  }

  return <OperacaoResolvida mpc={mpc} indiceAtual={indiceAtual} mpcs={mpcs.data} />;
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
