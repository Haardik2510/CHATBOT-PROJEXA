import { useState } from "react";
import { Outlet, NavLink, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import { Button } from "./ui/button";
import {
  MessageSquare,
  FileText,
  BarChart3,
  Users,
  LogOut,
  Menu,
  GraduationCap,
  Sparkles,
  Activity,
} from "lucide-react";

const shellMotion = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { type: "spring", stiffness: 100, damping: 20 },
};

export default function DashboardLayout() {
  const { user, logout, isFaculty, isAdmin } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const isChatRoute = location.pathname === "/chat";

  const navigation = [
    { name: "Research Chat", href: "/chat", icon: MessageSquare, show: true, note: "Living archive" },
    { name: "Library Registry", href: "/documents", icon: FileText, show: isFaculty, note: "Materials & indexing" },
    { name: "Scholar Analytics", href: "/analytics", icon: BarChart3, show: isFaculty, note: "Usage intelligence" },
    { name: "User Registry", href: "/users", icon: Users, show: isAdmin, note: "Community control" },
  ].filter((item) => item.show);

  const roleLabel = {
    student: "Student Scholar",
    faculty: "Faculty Lead",
    admin: "Platform Admin",
  };

  return (
    <div className="flex h-screen overflow-hidden bg-transparent">
      <AnimatePresence>
        {sidebarOpen ? (
          <motion.button
            type="button"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-40 bg-[#0b193c]/35 backdrop-blur-sm lg:hidden"
          />
        ) : null}
      </AnimatePresence>

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-screen w-[320px] shrink-0 flex-col scholar-hero border-r border-white/10 px-5 pb-5 pt-6 text-white transition-transform duration-300 lg:static lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <motion.div {...shellMotion} className="mb-6 flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="relative flex h-14 w-14 items-center justify-center rounded-[18px] border border-white/20 bg-white/10 shadow-[0_18px_32px_rgba(0,0,0,0.15)] backdrop-blur-xl">
              <GraduationCap className="h-7 w-7 text-white" />
              <div className="absolute -right-1 -top-1 rounded-full bg-[#6294ff] p-1 shadow-[0_0_18px_rgba(98,148,255,0.45)]">
                <Sparkles className="h-3 w-3 text-white" />
              </div>
            </div>
            <div>
              <p className="section-eyebrow !text-white/55">Scholar Pulse</p>
              <h1 className="text-xl font-extrabold text-white">KRMU Research OS</h1>
              <p className="mt-1 text-sm text-white/68">AI-integrated academic platform</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="rounded-full border border-white/15 bg-white/5 p-2 text-white/70 transition hover:bg-white/10 hover:text-white lg:hidden"
          >
            <Menu className="h-4 w-4" />
          </button>
        </motion.div>

        <motion.div
          {...shellMotion}
          transition={{ ...shellMotion.transition, delay: 0.05 }}
          className="mb-6 rounded-[22px] border border-white/12 bg-white/8 p-4 shadow-[0_24px_40px_rgba(0,0,0,0.12)] backdrop-blur-xl"
        >
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/20 bg-white/10 text-sm font-bold text-white">
              {user?.name?.charAt(0)?.toUpperCase() || "U"}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">{user?.name || "Unknown user"}</p>
              <p className="text-xs text-white/60">{roleLabel[user?.role] || "Scholar"}</p>
            </div>
          </div>
          <div className="rounded-[18px] border border-white/12 bg-[#6294ff]/12 p-3">
            <div className="mb-2 flex items-center gap-2">
              <Activity className="h-4 w-4 text-[#cfe0ff]" />
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/70">Pulse State</p>
            </div>
            <p className="text-sm leading-6 text-white/88">
              Search the knowledge archive, manage indexed materials, and review live academic intelligence from one shell.
            </p>
          </div>
        </motion.div>

        <nav className="flex-1 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
          {navigation.map((item, index) => (
            <motion.div
              key={item.href}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.08 * index }}
            >
              <NavLink
                to={item.href}
                onClick={() => setSidebarOpen(false)}
                data-testid={`nav-${item.name.toLowerCase().replace(/\s+/g, "-")}`}
                className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}
              >
                <item.icon className="h-5 w-5" />
                <div className="flex-1">
                  <p>{item.name}</p>
                  <p className={`text-xs ${location.pathname === item.href ? "text-[#0b193c]/70" : "text-white/50"}`}>{item.note}</p>
                </div>
              </NavLink>
            </motion.div>
          ))}
        </nav>

        <motion.div
          {...shellMotion}
          transition={{ ...shellMotion.transition, delay: 0.25 }}
          className="mt-5"
        >
          <Button
            variant="ghost"
            onClick={logout}
            data-testid="logout-btn"
            className="w-full justify-start rounded-full border border-white/12 bg-white/6 px-4 py-6 text-white/78 transition-all hover:bg-white/12 hover:text-white"
          >
            <LogOut className="mr-2 h-4 w-4" />
            Sign out
          </Button>
        </motion.div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden px-3 pb-3 pt-3 md:px-4 md:pb-4 md:pt-4">
        <div className="scholar-panel-strong flex min-h-0 flex-1 flex-col overflow-hidden">
          <header className="flex items-center justify-between border-b border-[#e1e7f5] px-4 py-3 lg:hidden">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="rounded-full border border-[#d7dff2] bg-white/75 p-2 text-[#0b193c]"
              data-testid="mobile-menu-btn"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="text-center">
              <p className="section-eyebrow">Scholar Pulse</p>
              <p className="text-sm font-extrabold text-[#0b193c]">KRMU Research OS</p>
            </div>
            <div className="h-9 w-9 rounded-full bg-[#eef3ff]" />
          </header>

          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 100, damping: 20 }}
            className={`flex-1 min-h-0 ${isChatRoute ? "overflow-hidden" : "overflow-y-auto overflow-x-hidden"}`}
          >
            <Outlet />
          </motion.div>
        </div>
      </main>
    </div>
  );
}
