import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Brain,
  GraduationCap,
  Mail,
  ShieldCheck,
  Sparkles,
  LibraryBig,
  ScanSearch,
  Orbit,
} from "lucide-react";

const portalOptions = [
  { value: "student", label: "Student" },
  { value: "faculty", label: "Teacher" },
  { value: "admin", label: "Admin" },
];

const heroItems = [
  {
    icon: ScanSearch,
    title: "Living Archive",
    description: "Search curriculum, policy, research, and campus knowledge in one continuous scholarly memory.",
  },
  {
    icon: LibraryBig,
    title: "Indexed Knowledge",
    description: "Every grounded answer traces back to seeded or uploaded academic material rather than vague web summaries.",
  },
  {
    icon: Sparkles,
    title: "AI Synthesis",
    description: "Structured answers, citations, and document-linked summaries designed for real academic workflows.",
  },
];

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
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.15 }}
      className="scholar-panel p-6 md:p-7"
    >
      <div className="mb-6 flex items-start gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-[16px] bg-[#0b193c] text-white shadow-[0_18px_28px_rgba(11,25,60,0.18)]">
          <ShieldCheck className="h-5 w-5" />
        </div>
        <div>
          <p className="section-eyebrow">Institutional Login</p>
          <h3 className="mt-1 text-xl font-extrabold text-[#0b193c]">Secure scholar access</h3>
          <p className="mt-2 text-sm leading-6 text-[#5c6b8d]">
            Sign in with email/password or Google. Both routes go through the same Supabase auth flow and preserve your assigned role.
          </p>
        </div>
      </div>

      {isElevatedPortal ? (
        <div className="mb-5 rounded-[14px] border border-[#6294ff]/25 bg-[#eef3ff] px-4 py-3 text-sm text-[#24428a]">
          {isLogin
            ? `Use an approved ${portalRole === "faculty" ? "teacher" : portalRole} account for this portal.`
            : "Teacher and admin portals still require a pre-approved role after account creation."}
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="space-y-4">
        {!isLogin ? (
          <div className="space-y-2">
            <Label htmlFor="name" className="text-[#23314f]">Full name</Label>
            <Input
              id="name"
              name="name"
              value={formData.name}
              onChange={onChange}
              placeholder="Enter your full name"
              className="input-field h-12"
            />
          </div>
        ) : null}

        <div className="space-y-2">
          <Label htmlFor="email" className="text-[#23314f]">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            value={formData.email}
            onChange={onChange}
            placeholder="you@krmangalam.edu.in"
            className="input-field h-12"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password" className="text-[#23314f]">Password</Label>
          <Input
            id="password"
            name="password"
            type="password"
            value={formData.password}
            onChange={onChange}
            placeholder="Enter your password"
            className="input-field h-12"
            required
          />
        </div>

        <motion.div whileTap={{ scale: 0.99 }} className="pt-2">
          <Button
            type="submit"
            data-testid="login-submit-btn"
            disabled={loading}
            className="btn-primary group relative h-12 w-full overflow-hidden text-base"
          >
            <span className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.22),transparent_58%)] opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
            <span className="relative z-10">
              {loading
                ? isLogin
                  ? "Signing in..."
                  : "Creating account..."
                : isLogin
                  ? `Enter ${portalRole === "faculty" ? "teacher" : portalRole} portal`
                  : `Create ${portalRole === "faculty" ? "teacher" : portalRole} account`}
            </span>
          </Button>
        </motion.div>
      </form>

      <div className="my-5 flex items-center gap-3">
        <div className="h-px flex-1 bg-[#d8e1f4]" />
        <span className="text-smallcaps text-xs text-[#7181a6]">or continue with</span>
        <div className="h-px flex-1 bg-[#d8e1f4]" />
      </div>

      <Button
        type="button"
        variant="outline"
        onClick={onGoogleLogin}
        disabled={loading}
        className="btn-secondary h-12 w-full border-[#d7dff2] bg-white/80"
      >
        <Mail className="mr-2 h-4 w-4" />
        Continue with Google
      </Button>

      {authError ? (
        <p className="mt-4 rounded-[12px] border border-[#b6171e]/15 bg-[#fff1f1] px-4 py-3 text-sm text-[#b6171e]" data-testid="auth-error">
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
  const [formData, setFormData] = useState({ name: "", email: "", password: "" });

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
    <div className="min-h-screen overflow-x-hidden bg-[#f8f9fa]">
      <div className="grid min-h-screen lg:grid-cols-[1.08fr_0.92fr]">
        <section className="scholar-hero relative hidden overflow-hidden px-10 py-10 text-white lg:flex lg:flex-col">
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute left-[8%] top-[10%] h-40 w-40 rounded-full border border-white/15 bg-white/8 blur-[2px] animate-breathe" />
            <div className="absolute right-[10%] top-[18%] h-64 w-64 rounded-full bg-[#6294ff]/18 blur-3xl animate-pulsebeam" />
            <div className="absolute bottom-[14%] left-[18%] h-72 w-72 rounded-full bg-[#b6171e]/14 blur-3xl animate-pulsebeam" />
            <div className="absolute bottom-[10%] right-[16%] h-48 w-48 rounded-full border border-white/12 bg-white/8 animate-float" />
          </div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 100, damping: 20 }}
            className="relative z-10 flex items-center gap-4"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-[18px] border border-white/15 bg-white/10 backdrop-blur-xl">
              <GraduationCap className="h-8 w-8 text-white" />
            </div>
            <div>
              <p className="text-smallcaps text-white/60">Scholar Pulse</p>
              <h1 className="text-2xl font-extrabold">K.R. Mangalam University</h1>
            </div>
          </motion.div>

          <div className="relative z-10 flex flex-1 items-center">
            <div className="grid w-full gap-10 xl:grid-cols-[1.08fr_0.92fr] xl:items-center">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.08 }}
              >
                <p className="section-eyebrow !text-white/55">The Living Archive</p>
                <h2 className="mt-3 max-w-xl text-5xl font-extrabold leading-[1.02]">
                  Tradition, synthesis, and AI research flow in a single scholarly interface.
                </h2>
                <p className="mt-5 max-w-xl text-base leading-7 text-white/74">
                  Scholar Pulse balances academic authority with kinetic intelligence. Search the archive, surface grounded answers,
                  and move from source material to synthesis without breaking context.
                </p>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.16 }}
                className="relative mx-auto flex h-[440px] w-[440px] items-center justify-center"
              >
                <div className="absolute inset-8 rounded-full border border-white/10 bg-white/5 backdrop-blur-xl" />
                <div className="absolute inset-16 rounded-full border border-[#6294ff]/35 shadow-[0_0_50px_rgba(98,148,255,0.22)] animate-breathe" />
                <div className="absolute inset-24 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.16),rgba(255,255,255,0.04),transparent_74%)]" />
                <div className="absolute inset-[30%] rounded-full border border-white/12 bg-white/10 backdrop-blur-xl animate-float" />
                <Brain className="relative z-10 h-24 w-24 text-white" />
                <Orbit className="absolute right-14 top-14 h-16 w-16 text-[#cfe0ff]" />
                <Sparkles className="absolute bottom-16 left-16 h-14 w-14 text-[#cfe0ff]" />
              </motion.div>
            </div>
          </div>

          <div className="relative z-10 grid gap-4 xl:grid-cols-3">
            {heroItems.map((item, index) => (
              <motion.div
                key={item.title}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.22 + index * 0.08 }}
                className="glass-card p-5 text-white"
              >
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-white/12 bg-white/12">
                  <item.icon className="h-5 w-5" />
                </div>
                <h3 className="text-lg font-extrabold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-white/72">{item.description}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="relative flex items-center justify-center px-5 py-8 md:px-8">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(98,148,255,0.18),transparent_26%),linear-gradient(180deg,#ffffff_0%,#f8f9fa_100%)]" />
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 100, damping: 20 }}
            className="relative z-10 w-full max-w-[560px]"
          >
            <div className="mb-6 lg:hidden">
              <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-[18px] bg-[#0b193c] text-white shadow-[0_16px_28px_rgba(11,25,60,0.18)]">
                <GraduationCap className="h-7 w-7" />
              </div>
              <p className="section-eyebrow">Scholar Pulse</p>
              <h1 className="mt-2 text-3xl font-extrabold text-[#0b193c]">KRMU Research OS</h1>
            </div>

            <div className="mb-6">
              <p className="section-eyebrow">Institutional Access</p>
              <h2 className="mt-2 text-4xl font-extrabold text-[#0b193c]">
                Enter the archive.
              </h2>
              <p className="mt-3 max-w-lg text-base leading-7 text-[#5c6b8d]">
                A single sign-in flow for students, teachers, and administrators, wrapped in the new Scholar Pulse experience.
              </p>
            </div>

            <div className="scholar-panel-strong p-5 md:p-6">
              <div className="mb-6 grid grid-cols-3 gap-2 rounded-full border border-[#d7dff2] bg-[#eef3ff]/70 p-2">
                {portalOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setPortalRole(option.value)}
                    className={`rounded-full px-3 py-3 text-sm font-semibold transition-all duration-300 ${
                      portalRole === option.value
                        ? "bg-[#0b193c] text-white shadow-[0_14px_28px_rgba(11,25,60,0.18)]"
                        : "text-[#4d5e82] hover:bg-white/75 hover:text-[#0b193c]"
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
                  className="text-sm font-semibold text-[#4d5e82] transition hover:text-[#6294ff]"
                  data-testid="toggle-auth-mode"
                >
                  {isLogin ? "Need an account instead? Create one here." : "Already have an account? Sign in instead."}
                </button>
              </div>
            </div>
          </motion.div>
        </section>
      </div>
    </div>
  );
}
