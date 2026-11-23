import { useAuth } from "./auth/AuthContext";
import { AuthPage } from "./pages/AuthPage";
import { Workspace } from "./pages/Workspace";

export function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="boot" aria-busy="true" />;
  return user ? <Workspace /> : <AuthPage />;
}
