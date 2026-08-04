import { Navigate, Outlet } from "react-router";

import { useAuth } from "../features/auth/useAuth";

export function AuthGuard() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}
