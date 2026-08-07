import { useMemo, useState } from "react";
import { Link } from "react-router";

import { resolverAlarmes, type CondicaoAtiva } from "./alarmes";
import { useCanalAoVivo } from "./CanalAoVivo";

/** Triângulo de alerta reaproveitado dos demais estados de falha da UI (mesmo path de
 *  `ConnectionsPage.tsx`/`FlowsPage.tsx`) — cor muda por severidade (`text-alarm`/`text-warn`),
 *  a forma e o rótulo textual ao lado permanecem os canais redundantes (DESIGN §Colors,
 *  "A Regra do Canal Redundante": nunca só cor). */
function IconeAlerta() {
  return (
    <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
      <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
    </svg>
  );
}

const ROTULO_SEVERIDADE: Record<CondicaoAtiva["severity"], string> = {
  alarm: "Alarme",
  warning: "Aviso",
};

const COR_SEVERIDADE: Record<CondicaoAtiva["severity"], string> = {
  alarm: "text-alarm",
  warning: "text-warn",
};

/** Contagem por severidade (§7.2-4) — só as duas severidades que `resolverAlarmes` produz. */
export function contarPorSeveridade(
  condicoes: readonly CondicaoAtiva[],
): Record<CondicaoAtiva["severity"], number> {
  return condicoes.reduce<Record<CondicaoAtiva["severity"], number>>(
    (contagem, condicao) => {
      contagem[condicao.severity] += 1;
      return contagem;
    },
    { warning: 0, alarm: 0 },
  );
}

function BadgeContagem({ severidade, total }: { severidade: CondicaoAtiva["severity"]; total: number }) {
  const rotulo = ROTULO_SEVERIDADE[severidade].toLowerCase();
  return (
    <span
      data-testid={`annunciator-contagem-${severidade}`}
      className={`flex items-center gap-1.5 ${COR_SEVERIDADE[severidade]}`}
    >
      <IconeAlerta />
      {total} {total === 1 ? rotulo : `${rotulo}s`}
    </span>
  );
}

/** Faixa anunciadora persistente (DESIGN.md §Layout; spec F5 §7.2-4; RF-705; ADR-020).
 *  Colapsada em 1 linha quando não há condição ativa. Com condições: contagem por severidade
 *  sempre visível + lista expansível (cor + ícone + texto por item — Regra do Canal
 *  Redundante); qualquer clique (resumo ou item) navega a `/eventos` — sem ACK, a única ação
 *  disponível numa condição ativa é ver o log completo (ADR-020). */
export function AnnunciatorBar() {
  const { eventos, flowStatus, mpcStates } = useCanalAoVivo();
  const [expandida, setExpandida] = useState(false);
  const condicoes = useMemo(
    () => resolverAlarmes(eventos, flowStatus, mpcStates, new Date()),
    [eventos, flowStatus, mpcStates],
  );

  if (condicoes.length === 0) {
    return (
      <div data-testid="annunciator" className="flex h-7 items-center border-b border-hairline bg-panel px-4">
        <span data-testid="annunciator-vazio" className="plaqueta text-xs text-fg-muted">
          Sem alarmes ativos
        </span>
      </div>
    );
  }

  const contagens = contarPorSeveridade(condicoes);

  return (
    <div data-testid="annunciator" className="border-b border-hairline bg-panel">
      <div className="flex h-7 items-center gap-4 px-4">
        <Link data-testid="annunciator-resumo" to="/eventos" className="flex items-center gap-4 text-xs">
          {contagens.alarm > 0 && <BadgeContagem severidade="alarm" total={contagens.alarm} />}
          {contagens.warning > 0 && <BadgeContagem severidade="warning" total={contagens.warning} />}
        </Link>
        <button
          type="button"
          data-testid="annunciator-expandir"
          aria-expanded={expandida}
          onClick={() => setExpandida((atual) => !atual)}
          className="plaqueta ml-auto text-[10px] text-fg-muted hover:text-fg"
        >
          {expandida ? "Recolher" : "Detalhar"}
        </button>
      </div>
      {expandida && (
        <ul data-testid="annunciator-lista" className="space-y-1 border-t border-hairline px-4 py-2">
          {condicoes.map((condicao, indice) => (
            <li key={`${condicao.origin}-${condicao.kind}-${indice}`} data-testid="annunciator-item">
              <Link
                to="/eventos"
                className={`flex items-center gap-2 py-0.5 text-xs ${COR_SEVERIDADE[condicao.severity]}`}
              >
                <IconeAlerta />
                <span className="plaqueta text-[10px]">{ROTULO_SEVERIDADE[condicao.severity]}</span>
                <span>{condicao.message}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
