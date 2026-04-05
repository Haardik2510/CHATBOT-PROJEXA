import { useEffect, useRef } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function AuthCallback() {
  const { handleGoogleCallback, user, authError } = useAuth();
  const attemptedRef = useRef(false);

  useEffect(() => {
    if (user || authError || attemptedRef.current) {
      return;
    }

    attemptedRef.current = true;
    handleGoogleCallback().catch((error) => {
      console.error("Google callback error:", error);
    });
  }, [authError, handleGoogleCallback, user]);

  if (user) {
    return <Navigate to="/chat" replace />;
  }

  if (authError) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-[#12151a] flex items-center justify-center">
      <div className="text-center">
        <div className="w-12 h-12 border-4 border-[#FFBA00] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-white font-heading">Completing sign-in...</p>
      </div>
    </div>
  );
}
