import { aplicarTema, useTema, type Tema } from "../../lib/theme";

function IconeSol() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  );
}

function IconeLua() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
    </svg>
  );
}

export function ThemeToggle() {
  const tema = useTema();
  const proximo: Tema = tema === "light" ? "dark" : "light";

  return (
    <button
      type="button"
      data-testid="theme-toggle"
      aria-label={proximo === "dark" ? "Ativar tema escuro" : "Ativar tema claro"}
      title={proximo === "dark" ? "Tema escuro" : "Tema claro"}
      onClick={() => {
        aplicarTema(proximo);
      }}
      className="focus-ring flex h-8 w-8 items-center justify-center rounded-pill border border-border bg-surface-2 text-fg-muted transition-colors duration-[var(--duration-fast)] hover:border-accent hover:text-accent"
    >
      {tema === "light" ? <IconeLua /> : <IconeSol />}
    </button>
  );
}
