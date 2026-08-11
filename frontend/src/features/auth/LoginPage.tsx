import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";

import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { ApiError } from "../../lib/api";
import { useAuth } from "./useAuth";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // a tela é remontada a cada volta ao /login; nunca herdar o erro da sessão anterior
  useEffect(() => setError(null), []);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Erro de comunicação com o servidor");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg bg-[image:var(--gradient-mesh)] bg-fixed p-6">
      <Card className="glass w-full max-w-md rounded-lg p-10 shadow-lg">
        <span
          aria-hidden="true"
          className="mb-6 block h-1 w-14 rounded-pill bg-[image:var(--gradient-accent)]"
        />
        <h1 className="font-display text-3xl font-bold tracking-tight">
          Ottima<span className="text-accent">System</span>
        </h1>
        <p className="plaqueta mt-2 text-xs text-fg-muted">Console de operação APC</p>
        <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="username">Usuário</Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              data-testid="login-username"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Senha</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              data-testid="login-password"
            />
          </div>
          {error && (
            // Regra do Canal Redundante: cor + ícone + texto (DESIGN.md §Colors)
            <p
              role="alert"
              data-testid="login-error"
              className="flex items-center gap-2 rounded-md bg-alarm-soft px-3 py-2 text-sm text-alarm"
            >
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1 15 14H1L8 1Zm-.75 5v4h1.5V6h-1.5Zm0 5.5V13h1.5v-1.5h-1.5Z" />
              </svg>
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={submitting} data-testid="login-submit">
            {submitting ? "Entrando…" : "Entrar"}
          </Button>
        </form>
        {/* Brand Commitments (PRODUCT.md): LFR só como assinatura */}
        <p className="mt-8 text-center text-xs text-fg-muted">by LFR Automação</p>
      </Card>
    </main>
  );
}
