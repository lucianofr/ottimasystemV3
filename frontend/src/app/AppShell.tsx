import { NavLink, Outlet, useNavigate } from "react-router";

import { Button } from "../components/ui/button";
import { ThemeToggle } from "../components/ui/theme-toggle";
import { useAuth } from "../features/auth/useAuth";
import { AnnunciatorBar } from "./AnnunciatorBar";
import { CanalAoVivoProvider } from "./CanalAoVivo";

/* Navegação em dois grupos (decisão A-10, spec F5 §7.3-1): Operação·Eventos são de
   operador (admin herda); Projetos·Conexões·Tags·Flows·Trend seguem visíveis para leitura —
   a ocultação de mutações é a tarefa 6.5. */
const NAV_OPERACAO = [
  { rotulo: "Operação", para: "/operacao", testid: "nav-operacao" },
  { rotulo: "Eventos", para: "/eventos", testid: "nav-eventos" },
] as const;

const NAV_ENGENHARIA = [
  { rotulo: "Projetos", para: "/engenharia/projetos", testid: "nav-projetos" },
  { rotulo: "Conexões", para: "/engenharia/conexoes", testid: "nav-conexoes" },
  { rotulo: "Tags", para: "/engenharia/tags", testid: "nav-tags" },
  { rotulo: "Flows", para: "/engenharia/flows", testid: "nav-flows" },
  { rotulo: "Trend", para: "/engenharia/trend", testid: "nav-trend" },
] as const;

/* Configurações gerais (RF-805): grupo próprio, só admin — operador nem vê o item (a rota
   também redireciona, SettingsPage). */
const NAV_ADMIN = [
  { rotulo: "Configurações", para: "/configuracoes", testid: "nav-configuracoes" },
] as const;

function ItemNav({ rotulo, para, testid }: { rotulo: string; para: string; testid: string }) {
  return (
    <NavLink
      to={para}
      data-testid={testid}
      className={({ isActive }) =>
        `plaqueta rounded-pill px-3 py-1.5 text-xs transition-colors duration-[var(--duration-fast)] ${
          isActive
            ? "bg-accent-soft text-accent-strong"
            : "text-fg-muted hover:bg-surface-2 hover:text-fg"
        }`
      }
    >
      {rotulo}
    </NavLink>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <CanalAoVivoProvider>
      <div className="flex min-h-screen flex-col bg-bg bg-[image:var(--gradient-mesh)] bg-fixed">
        <AnnunciatorBar />
        <header className="glass sticky top-0 z-20 flex h-14 items-center justify-between border-x-0 border-t-0 px-5">
          <span className="font-display text-base font-bold tracking-tight text-fg">
            Ottima<span className="text-accent">System</span>
          </span>
          <div className="flex items-center gap-3">
            <nav aria-label="Operação" className="flex items-center gap-1">
              {NAV_OPERACAO.map((item) => (
                <ItemNav key={item.para} {...item} />
              ))}
            </nav>
            <span aria-hidden="true" className="h-4 w-px bg-border" />
            <nav aria-label="Engenharia" className="flex items-center gap-1">
              {NAV_ENGENHARIA.map((item) => (
                <ItemNav key={item.para} {...item} />
              ))}
            </nav>
            {user?.role === "admin" && (
              <>
                <span aria-hidden="true" className="h-4 w-px bg-border" />
                <nav aria-label="Administração" className="flex items-center gap-1">
                  {NAV_ADMIN.map((item) => (
                    <ItemNav key={item.para} {...item} />
                  ))}
                </nav>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span data-testid="current-user" className="text-xs text-fg-muted">
              {user?.name} · {user?.role === "admin" ? "admin" : "operador"}
            </span>
            <ThemeToggle />
            <Button
              variant="outline"
              size="sm"
              data-testid="logout"
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
            >
              Sair
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1920px] flex-1 px-4 py-8">
          <Outlet />
        </main>
      </div>
    </CanalAoVivoProvider>
  );
}
