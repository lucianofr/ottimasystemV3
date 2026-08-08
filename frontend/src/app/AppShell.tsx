import { NavLink, Outlet, useNavigate } from "react-router";

import { Button } from "../components/ui/button";
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

function ItemNav({ rotulo, para, testid }: { rotulo: string; para: string; testid: string }) {
  return (
    <NavLink
      to={para}
      data-testid={testid}
      className={({ isActive }) =>
        `plaqueta border-b-2 py-1 text-xs ${
          isActive ? "border-accent text-fg" : "border-transparent text-fg-muted"
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
      <div className="flex min-h-screen flex-col">
        <AnnunciatorBar />
        <header className="flex h-12 items-center justify-between border-b border-hairline bg-panel px-4">
          <span className="plaqueta text-sm">OttimaSystem</span>
          <div className="flex items-center gap-5">
            <nav aria-label="Operação" className="flex items-center gap-5">
              {NAV_OPERACAO.map((item) => (
                <ItemNav key={item.para} {...item} />
              ))}
            </nav>
            <span aria-hidden="true" className="h-4 w-px bg-hairline" />
            <nav aria-label="Engenharia" className="flex items-center gap-5">
              {NAV_ENGENHARIA.map((item) => (
                <ItemNav key={item.para} {...item} />
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <span data-testid="current-user" className="text-xs text-fg-muted">
              {user?.name} · {user?.role === "admin" ? "admin" : "operador"}
            </span>
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
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </CanalAoVivoProvider>
  );
}
