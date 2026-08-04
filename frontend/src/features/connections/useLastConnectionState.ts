import { useQuery } from "@tanstack/react-query";

import { api, type EventOut } from "../../lib/api";

/** Uma única chamada por ciclo cobre todas as conexões do projeto: o teto é 5 conexões
 *  (RF-201), e `origin=conn:<id>&limit=1` seria ainda mais frágil — o mesmo `origin`
 *  também carrega eventos de subscription e de escrita rejeitada, então o evento mais
 *  recente daquele `origin` frequentemente NÃO é de comunicação. Filtrar por `kind` no
 *  cliente é o que garante o estado correto. Paliativo até o WS da F5 (spec F2 §9.1). */
const LIMITE_EVENTOS = 200;
const POLLING_MS = 5000;

const KIND_FALHA = "comm_failure";
const KIND_RESTABELECIDO = "comm_restored";

/** `reason` do `comm_failure` (spec F2 §3.4/§3.6) em pt-BR. */
const MOTIVOS: Record<string, string> = {
  watchdog_timeout: "watchdog congelado",
  session_lost: "sessão perdida",
  connect_failed: "falha ao conectar",
  cert_missing: "certificado do servidor ausente",
  cert_mismatch: "certificado do servidor divergente",
};

export interface UltimoEstado {
  /** Rótulo textual — Regra do Canal Redundante: cor nunca é o único canal. */
  rotulo: string;
  falha: boolean;
  ts: string;
}

const VAZIO: ReadonlyMap<number, UltimoEstado> = new Map();

function texto(payload: EventOut["payload"], chave: string): string | null {
  const valor = payload[chave];
  return typeof valor === "string" ? valor : null;
}

function idDaOrigem(origin: string): number | null {
  const casamento = /^conn:(\d+)$/.exec(origin);
  return casamento ? Number(casamento[1]) : null;
}

/** Eventos chegam em `ts` desc: o primeiro casamento por conexão é o último estado. */
function derivar(eventos: EventOut[]): ReadonlyMap<number, UltimoEstado> {
  const porConexao = new Map<number, UltimoEstado>();
  for (const evento of eventos) {
    const kind = texto(evento.payload, "kind");
    if (kind !== KIND_FALHA && kind !== KIND_RESTABELECIDO) continue;
    const id = idDaOrigem(evento.origin);
    if (id === null || porConexao.has(id)) continue;
    if (kind === KIND_RESTABELECIDO) {
      porConexao.set(id, { rotulo: "Comunicando", falha: false, ts: evento.ts });
      continue;
    }
    const motivo = texto(evento.payload, "reason");
    const motivoPtBr = (motivo && MOTIVOS[motivo]) ?? "motivo desconhecido";
    porConexao.set(id, { rotulo: `Falha: ${motivoPtBr}`, falha: true, ts: evento.ts });
  }
  return porConexao;
}

/** Último `comm_failure`/`comm_restored` por conexão, por polling de 5 s.
 *  `refetchIntervalInBackground` fica no default (false): aba oculta não faz polling. */
export function useLastConnectionState(): ReadonlyMap<number, UltimoEstado> {
  const { data } = useQuery({
    queryKey: ["events", "estado-conexoes"],
    queryFn: () => api<EventOut[]>(`/api/events?limit=${String(LIMITE_EVENTOS)}`),
    refetchInterval: POLLING_MS,
    select: derivar,
  });
  return data ?? VAZIO;
}
