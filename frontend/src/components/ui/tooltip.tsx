import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export interface TooltipContent {
  description: string;
  example?: string;
}

function TooltipBody({ content }: { content: TooltipContent }) {
  return (
    <>
      <span className="block">{content.description}</span>
      {content.example !== undefined && (
        <span className="mt-1.5 block text-fg-muted">Ex.: {content.example}</span>
      )}
    </>
  );
}

/**
 * Tooltip acessível: o gatilho é o próprio `children` (texto do rótulo do campo, per pedido
 * do usuário — "hover sobre o nome do parâmetro"), focável via teclado. Mostra em hover OU
 * foco, fecha em Esc/blur/mouseleave com um pequeno atraso (WCAG 2.2 SC 1.4.13 —
 * dismissible/hoverable/persistent); `role="tooltip"` + `aria-describedby` (WAI-ARIA APG).
 *
 * ponytail: posicionamento `absolute` simples (sem portal) — todo modal de bloco do editor
 * usa `<dialog>` nativo com `showModal()`. Portar pra `document.body` renderizaria ATRÁS do
 * dialog (o top layer do HTML sempre vence z-index, independente do valor); `position:fixed`
 * ainda seria clipado pelo `overflow-auto` do próprio `<dialog>` (clipping por overflow
 * aplica a qualquer descendente, fixed ou não). Pode cortar nas bordas do scroll do modal ou
 * dentro de containers roláveis aninhados (matriz da aba Modelos) — upgrade: portar pro
 * `<dialog>` com o scroll movido pra um wrapper interno, se incomodar na prática.
 *
 * Atraso de 150 ms ao fechar (em vez de fechar na hora): sem ele, o gap visual entre o
 * gatilho e o painel (mt-1.5) faz o mouse "sair" de ambos por um instante ao tentar entrar no
 * painel, fechando o tooltip antes do hover no painel registrar — quebra "hoverable".
 */
export function Tooltip({
  content,
  children,
  stopClick,
}: {
  content: TooltipContent;
  children: ReactNode;
  /** Quando o gatilho mora DENTRO do `<label>` de um checkbox (nunca associado por
   *  `htmlFor`, sempre por aninhamento — "MV com PID", "SP rastreia PV", "Habilitado" da
   *  matriz), clicar o texto do gatilho encaminha um clique nativo pro checkbox (mesma regra
   *  de "clicar o label ativa o controle" que faz `Label htmlFor=...` focar o input — só que
   *  aqui MUTA estado em vez de só focar). Achado no smoke test manual desta tarefa: ler o
   *  tooltip nunca deveria desmarcar "MV com PID" ou desabilitar um par da matriz. `true`
   *  suprime esse encaminhamento; omitido preserva "clicar o rótulo foca o input" nos ~40
   *  campos de texto que usam `Label` — comportamento nativo desejado ali. */
  stopClick?: boolean;
}) {
  const [aberto, setAberto] = useState(false);
  const id = useId();
  // `window.setTimeout`/`window.clearTimeout` explícitos (mesmo padrão de `CanalAoVivo.tsx`):
  // forçam a sobrecarga do DOM (retorna `number`), evitando a ambiguidade com o `setTimeout`
  // global do Node quando `@types/node` está no projeto.
  const timerFechar = useRef<number | null>(null);

  function limparTimer(): void {
    if (timerFechar.current !== null) {
      window.clearTimeout(timerFechar.current);
      timerFechar.current = null;
    }
  }

  function abrir(): void {
    limparTimer();
    setAberto(true);
  }

  function fecharComAtraso(): void {
    limparTimer();
    timerFechar.current = window.setTimeout(() => setAberto(false), 150);
  }

  // `preventDefault` + `stopPropagation`: sem eles, o Esc que fecha SÓ o tooltip também
  // fecha o `<dialog>` inteiro por baixo (todo modal de bloco do editor é um `<dialog>`
  // nativo — Esc é o "cancel" nativo dele; achado no smoke test manual desta tarefa,
  // fechar o tooltip nunca deveria levar o modal junto).
  useEffect(() => {
    if (!aberto) return;
    function aoTeclar(evento: KeyboardEvent): void {
      if (evento.key !== "Escape") return;
      evento.preventDefault();
      evento.stopPropagation();
      setAberto(false);
    }
    document.addEventListener("keydown", aoTeclar, { capture: true });
    return () => document.removeEventListener("keydown", aoTeclar, { capture: true });
  }, [aberto]);

  return (
    <span className="relative inline-block">
      <span
        tabIndex={0}
        aria-describedby={aberto ? id : undefined}
        className="cursor-help rounded-sm underline decoration-dotted decoration-fg-subtle underline-offset-2 focus-ring"
        onMouseEnter={abrir}
        onMouseLeave={fecharComAtraso}
        onFocus={abrir}
        onBlur={fecharComAtraso}
        onClick={stopClick === true ? (evento) => evento.preventDefault() : undefined}
      >
        {children}
      </span>
      {aberto && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 top-full z-20 mt-1.5 w-64 -translate-x-1/2 rounded-md border border-border bg-surface p-2.5 text-[11px] font-normal normal-case leading-snug tracking-normal text-fg shadow-md"
          onMouseEnter={abrir}
          onMouseLeave={fecharComAtraso}
          onClick={stopClick === true ? (evento) => evento.preventDefault() : undefined}
        >
          <TooltipBody content={content} />
        </span>
      )}
    </span>
  );
}
