import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "../lib/api";
import { supabase } from "../lib/supabase";

const AuthContext = createContext(null);

const TOKEN_STORAGE_KEY = "token";
const USER_STORAGE_KEY = "user";
const PORTAL_ROLE_STORAGE_KEY = "requested_portal_role";

const parseStoredUser = () => {
  const savedUser = localStorage.getItem(USER_STORAGE_KEY);
  if (!savedUser) {
    return null;
  }

  try {
    return JSON.parse(savedUser);
  } catch (error) {
    console.error("Failed to parse saved user:", error);
    localStorage.removeItem(USER_STORAGE_KEY);
    return null;
  }
};

const getStoredPortalRole = () => sessionStorage.getItem(PORTAL_ROLE_STORAGE_KEY) || "";

const setStoredPortalRole = (role) => {
  if (!role) {
    sessionStorage.removeItem(PORTAL_ROLE_STORAGE_KEY);
    return;
  }

  sessionStorage.setItem(PORTAL_ROLE_STORAGE_KEY, role);
};

const clearStoredPortalRole = () => sessionStorage.removeItem(PORTAL_ROLE_STORAGE_KEY);

const roleMatchesPortal = (userRole, requestedRole) => {
  if (!requestedRole || requestedRole === "student") {
    return true;
  }
  if (requestedRole === "faculty") {
    return userRole === "faculty" || userRole === "admin";
  }
  if (requestedRole === "admin") {
    return userRole === "admin";
  }
  return false;
};

const getErrorMessage = (error, fallbackMessage) => {
  const backendDetail = error?.response?.data?.detail;
  if (typeof backendDetail === "string") {
    return backendDetail;
  }

  const message = error?.message;
  if (typeof message === "string" && message.trim()) {
    return message;
  }

  return fallbackMessage;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(() => parseStoredUser());
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY));
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    axios.defaults.withCredentials = false;

    if (token) {
      axios.defaults.headers.common.Authorization = `Bearer ${token}`;
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      delete axios.defaults.headers.common.Authorization;
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }, [token]);

  useEffect(() => {
    if (user) {
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(USER_STORAGE_KEY);
    }
  }, [user]);

  const clearLocalSession = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const fetchCurrentUser = useCallback(async (authToken) => {
    if (!authToken) {
      return null;
    }

    const response = await axios.get(`${API}/auth/me`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
      timeout: 15000,
    });

    return response.data;
  }, []);

  const applyLocalSession = useCallback((sessionData) => {
    if (!sessionData?.access_token || !sessionData?.user) {
      return null;
    }

    setToken(sessionData.access_token);
    setUser(sessionData.user);
    setAuthError("");
    clearStoredPortalRole();
    return sessionData.user;
  }, []);

  const applySupabaseSession = useCallback(async (session) => {
    const accessToken = session?.access_token;
    if (!accessToken) {
      clearLocalSession();
      return null;
    }

    const profile = await fetchCurrentUser(accessToken);
    const requestedRole = getStoredPortalRole();
    if (!roleMatchesPortal(profile?.role, requestedRole)) {
      throw new Error(
        `This portal requires an approved ${requestedRole === "faculty" ? "teacher" : requestedRole} account.`
      );
    }
    setToken(accessToken);
    setUser(profile);
    setAuthError("");
    clearStoredPortalRole();
    return profile;
  }, [clearLocalSession, fetchCurrentUser]);

  useEffect(() => {
    let cancelled = false;

    const restoreSession = async () => {
      try {
        if (token) {
          const profile = await fetchCurrentUser(token);
          if (!cancelled && profile) {
            setUser(profile);
            setLoading(false);
            return;
          }
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Stored token restore error:", error);
          clearLocalSession();
        }
      }

      if (!supabase) {
        if (!cancelled) {
          setLoading(false);
        }
        return;
      }

      try {
        const { data } = await supabase.auth.getSession();
        if (!cancelled && data?.session?.access_token) {
          await applySupabaseSession(data.session);
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Supabase restore error:", error);
          clearLocalSession();
          setAuthError(getErrorMessage(error, "Unable to restore your session right now."));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    restoreSession();

    return () => {
      cancelled = true;
    };
  }, [applySupabaseSession, clearLocalSession, fetchCurrentUser, token]);

  useEffect(() => {
    if (!supabase) {
      return undefined;
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT") {
        clearLocalSession();
        setAuthError("");
        return;
      }

      if (session?.access_token) {
        setToken(session.access_token);
        fetchCurrentUser(session.access_token)
          .then((profile) => {
            setUser(profile);
            setAuthError("");
            clearStoredPortalRole();
          })
          .catch((error) => {
            console.error("Supabase auth state sync error:", error);
            clearLocalSession();
            setAuthError(getErrorMessage(error, "Unable to sync your session right now."));
          });
      }
    });

    return () => subscription.unsubscribe();
  }, [clearLocalSession, fetchCurrentUser]);

  const login = useCallback(async ({ email, password, role = "student" }) => {
    setStoredPortalRole(role);
    setLoading(true);
    setAuthError("");

    try {
      const response = await axios.post(
        `${API}/auth/login`,
        { email, password },
        { timeout: 15000 }
      );

      if (
        role !== "student" &&
        response.data?.user?.role !== role &&
        !(role === "faculty" && response.data?.user?.role === "admin")
      ) {
        throw new Error(
          `This portal requires an approved ${role === "faculty" ? "teacher" : role} account.`
        );
      }

      applyLocalSession(response.data);
      window.location.replace("/chat");
    } catch (error) {
      console.error("Email login error:", error);
      setAuthError(getErrorMessage(error, "Sign in failed. Please check your email and password."));
    } finally {
      setLoading(false);
    }
  }, [applyLocalSession]);

  const register = useCallback(async ({ name, email, password, role = "student" }) => {
    setStoredPortalRole(role);
    setLoading(true);
    setAuthError("");

    try {
      const response = await axios.post(
        `${API}/auth/register`,
        { name, email, password, role },
        { timeout: 20000 }
      );

      applyLocalSession(response.data);
      window.location.replace("/chat");
    } catch (error) {
      console.error("Email register error:", error);
      setAuthError(getErrorMessage(error, "Sign up failed. Please try again."));
    } finally {
      setLoading(false);
    }
  }, [applyLocalSession]);

  const loginWithGoogle = useCallback(async () => {
    if (!supabase) {
      setAuthError("Supabase authentication is not configured.");
      return;
    }

    setStoredPortalRole(getStoredPortalRole() || "student");
    setLoading(true);
    setAuthError("");

    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (error) {
        throw error;
      }
    } catch (error) {
      console.error("Google sign-in error:", error);
      setAuthError(getErrorMessage(error, "Google sign-in could not be started right now."));
      setLoading(false);
    }
  }, []);

  const handleGoogleCallback = useCallback(async () => {
    if (!supabase) {
      throw new Error("Supabase authentication is not configured.");
    }

    const { data, error } = await supabase.auth.getSession();
    if (error) {
      throw error;
    }

    if (!data?.session) {
      throw new Error("No Google session was returned.");
    }

    await applySupabaseSession(data.session);
    window.location.replace("/chat");
    return data.session;
  }, [applySupabaseSession]);

  const logout = useCallback(async () => {
    setLoading(true);
    setAuthError("");
    clearStoredPortalRole();
    clearLocalSession();
    sessionStorage.clear();

    try {
      if (supabase) {
        await supabase.auth.signOut();
      }
    } catch (error) {
      console.error("Logout error:", error);
    } finally {
      setLoading(false);
      window.location.replace("/login");
    }
  }, [clearLocalSession]);

  const value = useMemo(() => ({
    user,
    token,
    loading,
    authError,
    pendingVerification: null,
    setPortalIntent: setStoredPortalRole,
    setUser,
    setAuthError,
    login,
    register,
    verifySignUp: async () => {
      setAuthError("Email/password sign-up does not use verification codes.");
    },
    resendVerificationCode: async () => {
      setAuthError("Email/password sign-up does not use verification codes.");
    },
    cancelPendingVerification: () => {
      setAuthError("");
    },
    loginWithGoogle,
    handleGoogleCallback,
    retryAccess: handleGoogleCallback,
    logout,
    isAuthenticated: Boolean(user),
    isAdmin: user?.role === "admin",
    isFaculty: user?.role === "faculty" || user?.role === "admin",
  }), [authError, handleGoogleCallback, loading, login, loginWithGoogle, logout, register, token, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
