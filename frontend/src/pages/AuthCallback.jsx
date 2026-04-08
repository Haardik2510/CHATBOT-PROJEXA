import { useEffect, useRef } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import KRMULogo from "../components/KRMULogo";

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
    <div className="min-h-screen scholar-hero flex items-center justify-center">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-[22px] border border-white/15 bg-white/10 p-1.5 backdrop-blur-xl">
          <KRMULogo className="h-full w-full object-contain drop-shadow-[0_12px_20px_rgba(0,0,0,0.18)]" size={72} />
        </div>
        <div className="mx-auto mb-4 scholar-loader on-dark" />
        <p className="text-white font-heading">Completing sign-in...</p>
      </div>
    </div>
  );
}
