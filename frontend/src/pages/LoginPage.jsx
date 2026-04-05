import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  BookOpen,
  GraduationCap,
  Mail,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

const portalOptions = [
  { value: "student", label: "Student" },
  { value: "faculty", label: "Teacher" },
  { value: "admin", label: "Admin" },
];

const KRMULogo = () => (
  <div className="flex items-center gap-3">
    <div className="w-14 h-14 bg-[#FFBA00] rounded-xl flex items-center justify-center shadow-lg shadow-[#FFBA00]/20">
      <GraduationCap className="w-8 h-8 text-[#12151a]" />
    </div>
    <div>
      <h1 className="text-xl font-heading font-bold text-white">K.R. Mangalam</h1>
      <p className="text-xs text-[#FFBA00] uppercase tracking-widest">University</p>
    </div>
  </div>
);

const FeatureCard = ({ icon: Icon, title, description, delay }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.5, delay }}
    className="glass-card p-6 hover:border-[#FFBA00]/30 transition-all duration-300"
  >
    <div className="w-12 h-12 bg-[#FFBA00]/10 rounded-lg flex items-center justify-center mb-4">
      <Icon className="w-6 h-6 text-[#FFBA00]" />
    </div>
    <h3 className="text-lg font-heading font-semibold text-white mb-2">{title}</h3>
    <p className="text-[#9ca3af] text-sm leading-relaxed">{description}</p>
  </motion.div>
);

function AuthPanel({
  isLogin,
  portalRole,
  formData,
  loading,
  authError,
  onChange,
  onSubmit,
  onGoogleLogin,
}) {
  const isElevatedPortal = portalRole !== "student";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="rounded-2xl border border-[#2a3142] bg-[#12151a] p-6"
    >
      <div className="flex items-start gap-3 mb-5">
        <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-xl bg-[#FFBA00]/10">
          <ShieldCheck className="h-5 w-5 text-[#FFBA00]" />
        </div>
        <div>
          <h3 className="text-white font-semibold">Supabase authentication</h3>
          <p className="text-sm text-[#9ca3af] mt-1">
            Sign in with email/password or Google. Both routes go through the same Supabase auth flow.
          </p>
        </div>
      </div>

      {isElevatedPortal ? (
        <div className="mb-4 rounded-xl border border-[#FFBA00]/20 bg-[#FFBA00]/5 px-4 py-3 text-sm text-[#f3e2a3]">
          {isLogin
            ? `Use an approved ${portalRole === "faculty" ? "teacher" : portalRole} account for this portal.`
            : "Use an approved teacher or admin email for elevated access. The app will still check your assigned role after sign-up."}
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="space-y-4">
        {!isLogin ? (
          <div className="space-y-2">
            <Label htmlFor="name" className="text-[#d1d5db]">
              Full name
            </Label>
            <Input
              id="name"
              name="name"
              value={formData.name}
              onChange={onChange}
              placeholder="Enter your full name"
              className="h-11 border-[#2a3142] bg-[#0f131b] text-white placeholder:text-[#6b7280]"
            />
          </div>
        ) : null}

        <div className="space-y-2">
          <Label htmlFor="email" className="text-[#d1d5db]">
            Email
          </Label>
          <Input
            id="email"
            name="email"
            type="email"
            value={formData.email}
            onChange={onChange}
            placeholder="you@example.com"
            className="h-11 border-[#2a3142] bg-[#0f131b] text-white placeholder:text-[#6b7280]"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password" className="text-[#d1d5db]">
            Password
          </Label>
          <Input
            id="password"
            name="password"
            type="password"
            value={formData.password}
            onChange={onChange}
            placeholder="Enter your password"
            className="h-11 border-[#2a3142] bg-[#0f131b] text-white placeholder:text-[#6b7280]"
            required
          />
        </div>

        <Button
          type="submit"
          data-testid="login-submit-btn"
          className="w-full btn-primary h-12 font-semibold text-base"
          disabled={loading}
        >
          {loading
            ? isLogin
              ? "Signing in..."
              : "Creating account..."
            : isLogin
              ? `Sign in to ${portalRole === "faculty" ? "teacher" : portalRole} portal`
              : `Set up ${portalRole === "faculty" ? "teacher" : portalRole} account`}
        </Button>
      </form>

      <div className="my-5 flex items-center gap-3">
        <div className="h-px flex-1 bg-[#2a3142]" />
        <span className="text-xs uppercase tracking-widest text-[#6b7280]">or</span>
        <div className="h-px flex-1 bg-[#2a3142]" />
      </div>

      <Button
        type="button"
        variant="outline"
        onClick={onGoogleLogin}
        disabled={loading}
        className="w-full h-12 border-[#2a3142] bg-transparent text-[#d1d5db] hover:bg-[#1e2330]"
      >
        <Mail className="mr-2 h-4 w-4" />
        Continue with Google
      </Button>

      {authError ? (
        <p className="mt-4 text-sm text-red-400" data-testid="auth-error">
          {authError}
        </p>
      ) : null}
    </motion.div>
  );
}

export default function LoginPage() {
  const {
    login,
    register,
    loginWithGoogle,
    loading,
    authError,
    setAuthError,
    setPortalIntent,
  } = useAuth();

  const [isLogin, setIsLogin] = useState(true);
  const [portalRole, setPortalRole] = useState("student");
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
  });

  useEffect(() => {
    setPortalIntent(portalRole);
  }, [portalRole, setPortalIntent]);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((current) => ({ ...current, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setAuthError("");

    try {
      if (isLogin) {
        await login({
          email: formData.email.trim(),
          password: formData.password,
          role: portalRole,
        });
        return;
      }

      await register({
        name: formData.name.trim() || formData.email.trim(),
        email: formData.email.trim(),
        password: formData.password,
        role: portalRole,
      });
    } catch (error) {
      console.error("Auth form submit error:", error);
    }
  };

  return (
    <div className="min-h-screen bg-[#12151a] flex">
      <div className="hidden lg:flex lg:w-1/2 relative flex-col p-12 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-[#FFBA00]/5 via-transparent to-transparent" />
        <div className="absolute top-1/4 -left-32 w-64 h-64 bg-[#FFBA00]/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-0 w-96 h-96 bg-[#FFBA00]/5 rounded-full blur-3xl" />

        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="relative z-10"
        >
          <KRMULogo />
        </motion.div>

        <div className="flex-1 flex flex-col justify-center relative z-10">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
          >
            <h2 className="text-4xl font-heading font-bold text-white mb-4">
              SET Academic
              <span className="gradient-text"> Assistant</span>
            </h2>
            <p className="text-lg text-[#9ca3af] mb-8 max-w-md">
              Your intelligent knowledge companion for the School of Engineering & Technology
            </p>
          </motion.div>

          <div className="grid gap-4">
            <FeatureCard
              icon={Sparkles}
              title="AI-Powered Answers"
              description="Get instant, accurate responses from our RAG-powered knowledge base"
              delay={0.3}
            />
            <FeatureCard
              icon={BookOpen}
              title="Voice & Text Support"
              description="Ask questions using voice or text - whatever works best for you"
              delay={0.4}
            />
            <FeatureCard
              icon={Users}
              title="For Everyone"
              description="Designed for students, faculty, and administrators alike"
              delay={0.5}
            />
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.6 }}
          className="relative z-10 text-sm text-[#6b7280]"
        >
          (c) 2026 K.R. Mangalam University. All rights reserved.
        </motion.div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 md:p-8">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5 }}
          className="w-full max-w-xl"
        >
          <div className="lg:hidden text-center mb-8">
            <div className="flex justify-center mb-4">
              <KRMULogo />
            </div>
          </div>

          <div className="card-surface p-6 md:p-8">
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
            >
              <h2 className="text-2xl font-heading font-semibold text-white mb-2">
                {isLogin ? "Sign in to your account" : "Create your account"}
              </h2>
              <p className="text-[#6b7280] mb-6">
                Use Supabase email/password or Google authentication. Both routes enter the same app.
              </p>
            </motion.div>

            <div className="mb-6 grid grid-cols-3 gap-2 rounded-2xl border border-[#2a3142] bg-[#12151a] p-2">
              {portalOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setPortalRole(option.value)}
                  className={`rounded-xl px-3 py-3 text-sm font-medium transition-colors ${
                    portalRole === option.value
                      ? "bg-[#FFBA00] text-[#12151a]"
                      : "text-[#9ca3af] hover:bg-[#1e2330] hover:text-white"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <AuthPanel
              isLogin={isLogin}
              portalRole={portalRole}
              formData={formData}
              loading={loading}
              authError={authError}
              onChange={handleChange}
              onSubmit={handleSubmit}
              onGoogleLogin={loginWithGoogle}
            />

            <div className="mt-6 text-center">
              <button
                type="button"
                onClick={() => {
                  setIsLogin(!isLogin);
                  setAuthError("");
                }}
                className="text-[#9ca3af] hover:text-[#FFBA00] transition-colors text-sm"
                data-testid="toggle-auth-mode"
              >
                {isLogin
                  ? "Need an account instead? Switch to sign up"
                  : "Already have an account? Switch to sign in"}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
