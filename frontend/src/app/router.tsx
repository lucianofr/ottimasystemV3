import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage";
import { AuthProvider } from "../features/auth/useAuth";
import { ConnectionsPage } from "../features/connections/ConnectionsPage";
import { EventsPage } from "../features/events/EventsPage";
import { FlowEditorPage } from "../features/flows/FlowEditorPage";
import { FlowsPage } from "../features/flows/FlowsPage";
import { FuzzyOperatePage } from "../features/fuzzy/FuzzyOperatePage";
import { OperatePage } from "../features/operate/OperatePage";
import { OperateSelectorPage } from "../features/operate/OperateSelectorPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { TagsPage } from "../features/tags/TagsPage";
import { TrendPage } from "../features/trend/TrendPage";
import { AppShell } from "./AppShell";
import { AuthGuard } from "./AuthGuard";
import { HomePage } from "./HomePage";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AuthGuard />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/operacao" element={<OperateSelectorPage />} />
                <Route path="/operacao/:flowId/:blockId" element={<OperatePage />} />
                <Route path="/operacao/fuzzy" element={<FuzzyOperatePage />} />
                <Route path="/eventos" element={<EventsPage />} />
                <Route path="/engenharia/projetos" element={<ProjectsPage />} />
                <Route path="/engenharia/conexoes" element={<ConnectionsPage />} />
                <Route path="/engenharia/tags" element={<TagsPage />} />
                <Route path="/engenharia/flows" element={<FlowsPage />} />
                <Route path="/engenharia/flows/:flowId" element={<FlowEditorPage />} />
                <Route path="/engenharia/trend" element={<TrendPage />} />
                <Route path="/configuracoes" element={<SettingsPage />} />
              </Route>
              {/* dentro do guarda: rota desconhecida sem sessão vai direto a /login */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
