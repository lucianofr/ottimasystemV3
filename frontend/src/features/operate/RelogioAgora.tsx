import { useEffect, useState } from "react";

/**
 * Relógio "agora" do card principal do MPC (plano de melhorias, Fase 2 tarefa 2.1): tique de
 * 1 s, formato pt-BR `dd/mm/aaaa hh:mm:ss`. O operador lê o instante de referência do card —
 * fuso do navegador, sem ambiguidade — ao lado de Ts/horizontes e dos contadores de overrun
 * (`FaceplatePrincipal.tsx`).
 */

const INTERVALO_TIQUE_MS = 1000;

const FORMATO_DATA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const FORMATO_HORA = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function RelogioAgora() {
  const [agora, setAgora] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setAgora(new Date()), INTERVALO_TIQUE_MS);
    return () => window.clearInterval(id);
  }, []);

  return (
    <span className="process-value text-fg" data-testid="faceplate-relogio">
      {FORMATO_DATA.format(agora)} {FORMATO_HORA.format(agora)}
    </span>
  );
}
