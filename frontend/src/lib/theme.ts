import { useSyncExternalStore } from "react";

export type Tema = "light" | "dark";

const CHAVE = "ottima:tema";
const ouvintes = new Set<() => void>();

function ehTema(valor: string | null): valor is Tema {
  return valor === "light" || valor === "dark";
}

function lerTema(): Tema {
  const bruto = document.documentElement.dataset.theme ?? null;
  return ehTema(bruto) ? bruto : "light";
}

export function aplicarTema(tema: Tema): void {
  document.documentElement.dataset.theme = tema;
  localStorage.setItem(CHAVE, tema);
  ouvintes.forEach((ouvinte) => {
    ouvinte();
  });
}

export function aplicarTemaSalvo(): void {
  const salvo = localStorage.getItem(CHAVE);
  document.documentElement.dataset.theme = ehTema(salvo) ? salvo : "light";
}

/** Assinatura do tema para quem desenha fora do DOM (canvas do uPlot): sem isso o gráfico
 *  mantém as cores lidas na montagem depois de alternar claro/escuro. */
export function useTema(): Tema {
  return useSyncExternalStore(
    (aoMudar) => {
      ouvintes.add(aoMudar);
      return () => ouvintes.delete(aoMudar);
    },
    lerTema,
    () => "light" as const,
  );
}
