import type { MpcState } from "../../lib/contracts.gen";
import type { FaceplateVariavelProps } from "./FaceplateVariavel";
import type { MpcNodeOut } from "./useMpcs";

/**
 * Travessia projeção → props dos faceplates de variável, isolada de `OperatePage` para poder
 * ser testada pura (`faceplateVariavel.check.ts`): a página arrasta `TrendOperacao` e o CSS do
 * uPlot, que o runner de checks não resolve. Mesmo padrão de `trendOperacao.ts`/`pendencia.ts`.
 */
/** Monta a lista de props de `FaceplateVariavel` na ordem fixada pelo spec (MV → CV →
 *  Restrição → DV) a partir de `GET /api/operate/mpcs` (definição) e `mpc.state.vars`
 *  (valor ao vivo). `modos` cai no default de partida do deploy (LOCAL/MAN) enquanto o
 *  primeiro `mpc.state` não chega — mantém todo campo de escrita desabilitado até então,
 *  nunca finge um modo que ainda não foi confirmado. */
export function gradeDeVariaveis(
  mpc: MpcNodeOut,
  mpcState: MpcState | undefined,
  flowId: number,
  blockId: string,
): (FaceplateVariavelProps & { key: string })[] {
  const modos = mpcState?.modes ?? { local_remote: "local" as const, man_auto: "man" as const };
  const tsMpcSegundos = mpc.flow_ts_seconds * mpc.multiplier;
  const comum = { flowId, blockId, tsMpcSegundos, modos };
  return [
    ...mpc.variables.mvs.map((mv) => ({
      key: `mv-${mv.id}`,
      tipo: "mv" as const,
      definicao: {
        id: mv.id,
        name: mv.name,
        eu: mv.eu,
        limits: mv.limits,
        sp_limits: null,
        range: null,
        du_max: mv.du_max,
      },
      valor: mpcState?.vars[mv.id],
      ...comum,
    })),
    ...mpc.variables.cvs.map((cv) => ({
      key: `cv-${cv.id}`,
      tipo: "cv" as const,
      definicao: {
        id: cv.id,
        name: cv.name,
        eu: cv.eu,
        limits: null,
        sp_limits: cv.sp_limits,
        range: null,
        du_max: null,
      },
      valor: mpcState?.vars[cv.id],
      ...comum,
    })),
    ...mpc.variables.constraints.map((restricao) => ({
      key: `constraint-${restricao.id}`,
      tipo: "constraint" as const,
      definicao: {
        id: restricao.id,
        name: restricao.name,
        eu: restricao.eu,
        limits: null,
        sp_limits: null,
        range: restricao.range,
        du_max: null,
      },
      valor: mpcState?.vars[restricao.id],
      ...comum,
    })),
    ...mpc.variables.dvs.map((dv) => ({
      key: `dv-${dv.id}`,
      tipo: "dv" as const,
      definicao: {
        id: dv.id,
        name: dv.name,
        eu: dv.eu,
        limits: null,
        sp_limits: null,
        // `range` da DV é opcional (spec §4.2-5, RFC-16): quando publicado alimenta a mesma
        // barra da Restrição; ausente, `faixaDaEscala` devolve null e o faceplate fica só com
        // PV + EU. Fixar `null` aqui anulava a faixa antes de `faixaDaEscala` poder vê-la.
        range: dv.range ?? null,
        du_max: null,
      },
      valor: mpcState?.vars[dv.id],
      ...comum,
    })),
  ];
}
