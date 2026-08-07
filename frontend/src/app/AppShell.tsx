import { NavLink, Outlet, useNavigate } from "react-router";

import { Button } from "../components/ui/button";
import { useAuth } from "../features/auth/useAuth";
import { AnnunciatorBar } from "./AnnunciatorBar";
import { CanalAoVivoProvider } from "./CanalAoVivo";

/* Navegação de Engenharia: plaqueta discreta, ativo no azul único (DESIGN.md §Primary).
   Visível para admin e operador — ADR-015; a ocultação de mutações é a tarefa 6.5. */
const NAV_ENGENHARIA = [
  { rotulo: "Conexões", para: "/engenharia/conexoes", testid: "nav-conexoes" },
  { rotulo: "Tags", para: "/engenharia/tags", testid: "nav-tags" },
  { rotulo: "Flows", para: "/engenharia/flows", testid: "nav-flows" },
  { rotulo: "Trend", para: "/engenharia/trend", testid: "nav-trend" },
] as const;

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <CanalAoVivoProvider>
      <div className="flex min-h-screen flex-col">
        <AnnunciatorBar />
        <header className="flex h-12 items-center justify-between border-b border-hairline bg-panel px-4">
          <span className="plaqueta text-sm">OttimaSystem</span>
          <nav aria-label="Engenharia" className="flex items-center gap-5">
            {NAV_ENGENHARIA.map((item) => (
              <NavLink
                key={item.para}
                to={item.para}
                data-testid={item.testid}
                className={({ isActive }) =>
                  `plaqueta border-b-2 py-1 text-xs ${
                    isActive ? "border-accent text-fg" : "border-transparent text-fg-muted"
                  }`
                }
              >
                {item.rotulo}
              </NavLink>
            ))}
          </nav>
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
