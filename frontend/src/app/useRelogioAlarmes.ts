import { useEffect, useState } from "react";

/**
 * Tique de TTL sem re-render global (tarefa 6.1 do plano F6b; spec F6 §6.6-1, débito 1 de
 * frontend da F5; RF-705). A família TTL de `resolverAlarmes` (`mpc_arm_failed`, 60 s,
 * `alarmes.ts:220-229`) só reavalia quando `agora` muda — sem mensagem nova no canal, a
 * condição fica acesa numa tela silenciosa até a próxima varredura. A correção é um relógio
 * que tique a cada `INTERVALO_TIQUE_ALARMES_MS`; a assinatura de `resolverAlarmes` não muda
 * (já recebe `agora: Date`, `alarmes.ts:233-238`, continua pura).
 *
 * O relógio vive em **estado próprio**, fora do `value` de `EstadoContext.Provider`
 * (`CanalAoVivo.tsx:702`): bumpar `estado` a cada tique re-renderizaria toda a árvore de
 * `useCanalAoVivo()` — inclusive `TrendOperacao`, que desmontaria o container do uPlot a
 * cada 5 s (o próprio débito que esta tarefa fecha). `useRelogioAlarmes` é chamado direto
 * por quem deriva alarmes (hoje só `AnnunciatorBar`): o `useState` que este hook cria é
 * local ao componente que o chama — um tique só re-renderiza ESSE componente, nunca os
 * irmãos dele na árvore (`AppShell.tsx` monta `<AnnunciatorBar />` e `<Outlet />`, onde vive
 * `TrendOperacao`, como irmãos sob o mesmo `CanalAoVivoProvider` — fibers distintos, sem
 * relação de pai/filho). Não existe contexto novo aqui porque não faz falta: dono e
 * consumidor do relógio são o mesmo componente.
 */

/** Spec F6 §6.6-1 / plano F6b tarefa 6.1: "Tique de 5 s"; o roteiro B-F6-11 espera
 *  `wait(6000)` (> um tique) para cobrir a janela (`docs/plans/tests-e2e-f6.md:201`). */
export const INTERVALO_TIQUE_ALARMES_MS = 5_000;

/** Relógio como dependência injetável (mesmo padrão de `AmbienteAoVivo`,
 *  `features/flows/useFlowStatus.ts:153`): em produção é `window.setInterval`; no check
 *  (`canalAoVivo.check.ts`) é um dublê que só avança quando o teste manda — um teste da
 *  janela de 60 s não pode esperar 60 s de verdade. */
export interface AmbienteRelogio {
  agora: () => Date;
  agendar: (acao: () => void, intervaloMs: number) => number;
  cancelar: (id: number) => void;
}

const AMBIENTE_RELOGIO_BROWSER: AmbienteRelogio = {
  agora: () => new Date(),
  agendar: (acao, intervaloMs) => window.setInterval(acao, intervaloMs),
  cancelar: (id) => {
    window.clearInterval(id);
  },
};

export interface CicloRelogioAlarmes {
  desmontar: () => void;
}

/** Núcleo testável sem React: agenda UM `setInterval` (o primitivo nativo certo para "a
 *  cada N ms" — não um `setTimeout` que se reagenda) que chama `aplicar(ambiente.agora())`
 *  a cada tique. `desmontar` cancela o mesmo id — sem isso, cada montagem de quem chama
 *  `useRelogioAlarmes` empilharia mais um intervalo vivo por cima do anterior. */
export function criarRelogioAlarmes(
  aplicar: (agora: Date) => void,
  ambiente: AmbienteRelogio = AMBIENTE_RELOGIO_BROWSER,
): CicloRelogioAlarmes {
  const id = ambiente.agendar(() => aplicar(ambiente.agora()), INTERVALO_TIQUE_ALARMES_MS);
  return {
    desmontar: () => ambiente.cancelar(id),
  };
}

/** Composição fina (sem lógica própria a testar — `criarRelogioAlarmes` acima já cobre o
 *  núcleo): `useState` local ao componente que chama este hook; `useEffect` monta o relógio
 *  no mount e desmonta no cleanup, sem reagir a nenhuma dependência externa. */
export function useRelogioAlarmes(): Date {
  const [agora, setAgora] = useState<Date>(() => new Date());
  useEffect(() => {
    const ciclo = criarRelogioAlarmes(setAgora);
    return () => ciclo.desmontar();
  }, []);
  return agora;
}
