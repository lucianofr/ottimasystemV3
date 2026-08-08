/**
 * `state` do ramo `estadoPublicado` é `unknown`, não `MpcState` (débito §6.6-3 fechado):
 * `lerCaminho` só lê por caminho de pontos, então o redutor nunca precisa de um `MpcState`
 * estruturalmente completo — exigir esse tipo obrigava os chamadores que só têm um recorte
 * (ex. `FaceplateVariavel`, que republica um único `vars.<id>`) a forjar um objeto inteiro e
 * fazer double-cast só para satisfazer o compilador. Ver `FaceplateVariavel.tsx`.
 */

/**
 * `reduzirPendencia` — tarefa 4.2 do plano F5b (spec F5 §7.4-4; F5R-18; Regra do Estado
 * Publicado). Redutor PURO: sem timers internos, sem estado de módulo, sem I/O — `agora` é o
 * único relógio, injetado pelo chamador (4.3/4.4 disparam "tique" a cada `mpc.state`/tick de UI).
 *
 * 1 gesto, sem diálogo: "comandar" abre a pendência com o valor em fantasma; "estadoPublicado"
 * materializa (pendência cai para `null`) quando o `mpc.state` seguinte confirma o alvo, e é
 * ignorado (pendência inalterada) quando não confirma — nunca cancela por um estado qualquer,
 * só por confirmação ou expiração; "tique" reverte ao publicado quando a janela vence.
 *
 * Janela = `max(3 × Ts_mpc, 5s)` — estritamente maior que a confirmação do runtime
 * (`CONFIRM_MISSES_LIMIT = 2` ticks, `mpc_arming.py:34`), para o desfecho publicado
 * (confirmação ou `mpc_arm_failed`) sempre chegar antes do timeout do cliente.
 */

/** `valorComandado` é primitivo por contrato (`number | string | boolean` — posição de
 *  comutador ou valor de SP/MV; nunca objeto/array). A assinatura pública é a fixada pelo
 *  plano (`unknown`, tarefa 4.2) — não estreitar o tipo aqui divergiria dela; a comparação
 *  por igualdade estrita em `estadoPublicado` depende dessa premissa permanecer verdadeira. */
export type Pendencia = { alvo: string; valorComandado: unknown; expiraEm: number };

type AcaoPendencia =
  | { tipo: "comandar"; alvo: string; valor: unknown; tsMpcSegundos: number; agora: number }
  | { tipo: "estadoPublicado"; state: unknown; agora: number }
  | { tipo: "tique"; agora: number };

const PISO_JANELA_SEGUNDOS = 5;

/** `alvo` é um caminho com pontos dentro do `MpcState` publicado (ex.: "modes.local_remote",
 *  "vars.MV1.v", "vars.CV1.sp") — o mesmo alvo endereça tanto comutadores de posição quanto
 *  variáveis, sem o redutor conhecer a forma de cada faceplate (4.3/4.4 escolhem o caminho).
 *  Caminho que não existe no estado (alvo inválido ou variável ainda não publicada) resolve
 *  para `undefined`, que nunca é `=== valorComandado` — a pendência só expira pela janela,
 *  nunca trava (mesmo fail-safe de um estado que não confirma). */
function lerCaminho(objeto: unknown, caminho: string): unknown {
  return caminho.split(".").reduce<unknown>((atual, chave) => {
    if (atual === null || typeof atual !== "object") return undefined;
    return (atual as Record<string, unknown>)[chave];
  }, objeto);
}

export function reduzirPendencia(atual: Pendencia | null, acao: AcaoPendencia): Pendencia | null {
  switch (acao.tipo) {
    case "comandar": {
      const janelaSegundos = Math.max(3 * acao.tsMpcSegundos, PISO_JANELA_SEGUNDOS);
      return { alvo: acao.alvo, valorComandado: acao.valor, expiraEm: acao.agora + janelaSegundos * 1000 };
    }
    case "estadoPublicado": {
      if (atual === null) return null;
      // Igualdade estrita: correta enquanto `valorComandado` for primitivo (contrato acima).
      const confirmado = lerCaminho(acao.state, atual.alvo) === atual.valorComandado;
      return confirmado ? null : atual;
    }
    case "tique": {
      if (atual === null) return null;
      return acao.agora >= atual.expiraEm ? null : atual;
    }
  }
}
