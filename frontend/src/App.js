import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import LoginPage from "./pages/LoginPage";
import AuthCallback from "./pages/AuthCallback";
import DashboardLayout from "./components/DashboardLayout";
import ChatView from "./pages/ChatView";
import DocumentsView from "./pages/DocumentsView";
import AnalyticsView from "./pages/AnalyticsView";
import UsersView from "./pages/UsersView";
import "./App.css";

const LoadingScreen = () => (
  <div className="min-h-screen bg-[#12151a] flex items-center justify-center">
    <div className="text-center">
      <div className="w-12 h-12 border-4 border-[#FFBA00] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
      <p className="text-white font-heading">Loading...</p>
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
              background: "#1a1e26",
              border: "1px solid #2a3142",
              color: "#fafafa",
            },
          }}
        />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
