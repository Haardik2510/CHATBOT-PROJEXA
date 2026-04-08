import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import LoginPage from "./pages/LoginPage";
import AuthCallback from "./pages/AuthCallback";
import DashboardLayout from "./components/DashboardLayout";
import KRMULogo from "./components/KRMULogo";
import ChatView from "./pages/ChatView";
import DocumentsView from "./pages/DocumentsView";
import AnalyticsView from "./pages/AnalyticsView";
import UsersView from "./pages/UsersView";
import { API } from "./lib/api";
import "./App.css";

const LoadingScreen = () => (
  <div className="min-h-screen scholar-hero flex items-center justify-center">
    <div className="text-center">
      <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-[22px] border border-white/15 bg-white/10 p-1.5 backdrop-blur-xl">
        <KRMULogo className="h-full w-full object-contain drop-shadow-[0_12px_20px_rgba(0,0,0,0.18)]" size={72} />
      </div>
      <div className="mx-auto mb-4 scholar-loader on-dark" />
      <p className="font-heading text-white">Entering Scholar Pulse...</p>
    </div>
  </div>
);

const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <LoadingScreen />;
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to="/chat" replace />;
  }

  return children;
};

function AppRouter() {
  const { user, loading } = useAuth();

  useEffect(() => {
    if (!user) {
      return undefined;
    }

    const heartbeat = () => {
      fetch(`${API}/ping`, {
        method: "GET",
        cache: "no-store",
      }).catch(() => undefined);
    };

    heartbeat();
    const interval = window.setInterval(heartbeat, 10 * 60 * 1000);
    return () => window.clearInterval(interval);
  }, [user]);

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/chat" replace /> : loading ? <LoadingScreen /> : <LoginPage />}
      />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatView />} />
        <Route
          path="documents"
          element={
            <ProtectedRoute allowedRoles={["faculty", "admin"]}>
              <DocumentsView />
            </ProtectedRoute>
          }
        />
        <Route
          path="analytics"
          element={
            <ProtectedRoute allowedRoles={["faculty", "admin"]}>
              <AnalyticsView />
            </ProtectedRoute>
          }
        />
        <Route
          path="users"
          element={
            <ProtectedRoute allowedRoles={["admin"]}>
              <UsersView />
            </ProtectedRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRouter />
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: "rgba(255,255,255,0.86)",
              border: "1px solid rgba(215,223,242,0.95)",
              color: "#0b193c",
              backdropFilter: "blur(18px)",
              boxShadow: "0 24px 40px rgba(11,25,60,0.08)",
            },
          }}
        />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
