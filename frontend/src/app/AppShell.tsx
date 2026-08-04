import { Outlet, useNavigate } from "react-router";

import { Button } from "../components/ui/button";
import { useAuth } from "../features/auth/useAuth";
import { AnnunciatorBar } from "./AnnunciatorBar";

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen flex-col">
      <AnnunciatorBar />
      <header className="flex h-12 items-center justify-between border-b border-hairline bg-panel px-4">
        <span className="plaqueta text-sm">OttimaSystem</span>
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
  );
}
