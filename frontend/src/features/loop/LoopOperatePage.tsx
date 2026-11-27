import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router";

import { useAssinatura, useCanalAoVivo } from "../../app/CanalAoVivo";
import { Card } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { useFlow } from "../flows/useFlows";
import { FaceplateMalha } from "./FaceplateMalha";
import { malhaAoVivo, motivoSemEstado, resolverSelecao } from "./malhaLogica";
import { SintoniaVigente } from "./SintoniaVigente";
import { TrendMalha } from "./TrendMalha";
import { rotuloLoop, useLoops, useLoopConfig } from "./useLoops";
import type { LoopNodeOut } from "./types";

/**
 * PID MALHA (ADR-039 §4.10, RF-645) — combobox da malha do projeto ativo (`?flow=&bloco=`,
 * mesmo padrão de `FuzzyOperatePage`), faceplate e sintonia somente leitura (edição é do
 * editor de flow). O que decide (seleção, ao vivo, escala) mora em `malhaLogica.ts`.
 */

function chaveNo(no: LoopNodeOut): string {
  return `${String(no.flow_id)}/${no.block_id}`;
}

function MalhaSelecionada({ flowId, blockId }: { flowId: number; blockId: string }) {
  useAssinatura({ loop_state: [`${String(flowId)}/${blockId}`], flow_status: [flowId] });
  const canal = useCanalAoVivo();
  const config = useLoopConfig(flowId, blockId);
  const flow = useFlow(flowId);

  // v2 multicanal: um LoopState por canal na mesma assinatura; SISO é o caso n_loops=1.
  const nLoops = config.data?.n_loops ?? 1;
  const estados = useMemo(
    () =>
      Array.from({ length: nLoops }, (_, i) =>
        canal.loopStates.get(`${String(flowId)}/${blockId}:${String(i)}`),
      ),
    [canal.loopStates, flowId, blockId, nLoops],
  );
  // O portão lê só o canal 0, que não depende da config: o canal 0 novo prova a varredura
  // inteira, e "primeiro definido de `estados`" mudaria de canal quando `n_loops` chegasse.
  const estado0 = canal.loopStates.get(`${String(flowId)}/${blockId}:0`);
  const estadoFlow = canal.flowStatus.get(flowId)?.state;

  // `tsBase`: semeada na montagem (síncrono) e, enquanto NÃO está ao vivo, segue o quadro
  // retido; só congela ao vivo. Assim, no render em que o canal reabre ou o flow volta a
  // `running` (o runtime publica `running` antes da 1ª varredura, `scheduler.py:246`), a base
  // já é o retido e nada antigo passa por vivo. Seguir também `estado0` cobre um quadro que
  // chegue depois do `stopped` (assinaturas distintas no hub não garantem ordem).
  const tsBase = useRef(estado0?.ts);
  const aoVivo = malhaAoVivo({
    canal: canal.estado,
    estadoFlow,
    estado: estado0,
    tsBase: tsBase.current,
  });
  useEffect(() => {
    if (!aoVivo) tsBase.current = estado0?.ts;
  }, [aoVivo, estado0]);
  const motivo = motivoSemEstado(canal.estado, estadoFlow, flow.data?.desired_state);

  return (
    <div className="space-y-4">
      <FaceplateMalha
        flowId={flowId}
        blockId={blockId}
        config={config.data}
        estados={estados}
        aoVivo={aoVivo}
        motivoSemEstado={motivo}
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        {config.data !== undefined && <SintoniaVigente config={config.data} />}
        {/* Fora de `aoVivo`: o histórico aparece com o flow parado; só a borda viva é portada. */}
        <div className="lg:col-start-2">
          <TrendMalha flowId={flowId} blockId={blockId} nLoops={nLoops} estados={estados} aoVivo={aoVivo} />
        </div>
      </div>
    </div>
  );
}

export function LoopOperatePage() {
  const loops = useLoops();
  const [searchParams, setSearchParams] = useSearchParams();
  const flowParam = searchParams.get("flow");
  const blocoParam = searchParams.get("bloco");
  const selecionada = resolverSelecao(loops.data ?? [], flowParam, blocoParam);

  // URL sem seleção válida (primeiro acesso, link velho, bloco apagado): fixa a malha resolvida
  // na URL com `replace`, para o combobox e o link refletirem o que está na tela.
  useEffect(() => {
    if (!loops.isSuccess || selecionada === null) return;
    if (String(selecionada.flow_id) === flowParam && selecionada.block_id === blocoParam) return;
    setSearchParams(
      { flow: String(selecionada.flow_id), bloco: selecionada.block_id },
      { replace: true },
    );
  }, [loops.isSuccess, selecionada, flowParam, blocoParam, setSearchParams]);

  let corpo;
  if (loops.isPending) {
    corpo = (
      <Card className="max-w-lg p-6">
        <p className="text-sm text-fg-muted">Carregando…</p>
      </Card>
    );
  } else if (loops.isError) {
    corpo = (
      <Card className="max-w-lg p-6">
        <p role="alert" className="text-sm text-alarm">
          Falha ao listar as malhas do projeto ativo
        </p>
      </Card>
    );
  } else if (selecionada === null) {
    corpo = (
      <Card className="max-w-lg p-6">
        <p className="text-sm text-fg-muted">
          Nenhuma malha no projeto ativo — arraste um bloco PID Malha no editor de flow.
        </p>
      </Card>
    );
  } else {
    corpo = (
      <MalhaSelecionada
        key={chaveNo(selecionada)}
        flowId={selecionada.flow_id}
        blockId={selecionada.block_id}
      />
    );
  }

  return (
    <section className="space-y-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="plaqueta text-sm">Malha</h1>
        <Select
          aria-label="Malha"
          data-testid="loop-combobox"
          className="h-8 w-72"
          value={selecionada === null ? "" : chaveNo(selecionada)}
          onChange={(evento) => {
            const no = (loops.data ?? []).find((n) => chaveNo(n) === evento.target.value);
            if (no !== undefined) setSearchParams({ flow: String(no.flow_id), bloco: no.block_id });
          }}
        >
          {(loops.data ?? []).map((no) => (
            <option key={chaveNo(no)} value={chaveNo(no)}>
              {rotuloLoop(no)}
            </option>
          ))}
        </Select>
      </div>
      {corpo}
    </section>
  );
}
