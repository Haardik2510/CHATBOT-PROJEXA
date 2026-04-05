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
  X,
  GraduationCap,
  ChevronRight,
} from "lucide-react";

export default function DashboardLayout() {
  const { user, logout, isFaculty, isAdmin } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const navigation = [
    {
      name: "Chat",
      href: "/chat",
      icon: MessageSquare,
      show: true,
    },
    {
      name: "Documents",
      href: "/documents",
      icon: FileText,
      show: isFaculty,
    },
    {
      name: "Analytics",
      href: "/analytics",
      icon: BarChart3,
      show: isFaculty,
    },
    {
      name: "Users",
      href: "/users",
      icon: Users,
      show: isAdmin,
    },
  ].filter((item) => item.show);

  const roleColors = {
    student: "bg-blue-500/20 text-blue-400 border border-blue-500/30",
    faculty: "bg-green-500/20 text-green-400 border border-green-500/30",
    admin: "bg-[#FFBA00]/20 text-[#FFBA00] border border-[#FFBA00]/30",
  };

  return (
    <div className="min-h-screen bg-[#12151a] flex">
      {/* Mobile sidebar backdrop */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside
        className={`
          fixed lg:static inset-y-0 left-0 z-50
          w-64 bg-[#0f1115] border-r border-[#1e2330]
          transform transition-transform duration-300 ease-out
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
        `}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="p-5 border-b border-[#1e2330]">
            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-center gap-3"
            >
              <div className="w-11 h-11 bg-[#FFBA00] rounded-xl flex items-center justify-center shadow-lg shadow-[#FFBA00]/10">
                <GraduationCap className="w-6 h-6 text-[#12151a]" />
              </div>
              <div>
                <h1 className="font-heading font-bold text-white text-sm">
                  SET Chatbot
                </h1>
                <p className="text-[10px] text-[#FFBA00] uppercase tracking-wider font-medium">
                  K.R. Mangalam University
                </p>
              </div>
            </motion.div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-1">
            {navigation.map((item, index) => {
              const isActive = location.pathname === item.href;
              return (
                <motion.div
                  key={item.name}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                >
                  <NavLink
                    to={item.href}
                    onClick={() => setSidebarOpen(false)}
                    data-testid={`nav-${item.name.toLowerCase()}`}
                    className={`
                      sidebar-link
                      ${isActive ? "active" : ""}
                    `}
                  >
                    <item.icon className="w-5 h-5" />
                    <span className="flex-1 font-medium">{item.name}</span>
                    {isActive && (
                      <motion.div
                        layoutId="activeIndicator"
                        className="text-[#FFBA00]"
                      >
                        <ChevronRight className="w-4 h-4" />
                      </motion.div>
                    )}
                  </NavLink>
                </motion.div>
              );
            })}
          </nav>

          {/* User section */}
          <div className="p-4 border-t border-[#1e2330]">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 mb-4"
            >
              {user?.picture ? (
                <img
                  src={user.picture}
                  alt={user.name}
                  className="w-10 h-10 rounded-full object-cover"
                />
              ) : (
                <div className="w-10 h-10 bg-[#FFBA00]/10 rounded-full flex items-center justify-center border border-[#FFBA00]/30">
                  <span className="text-sm font-bold text-[#FFBA00]">
                    {user?.name?.charAt(0)?.toUpperCase() || "U"}
                  </span>
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {user?.name}
                </p>
                <span
                  className={`inline-block text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wider font-bold ${
                    roleColors[user?.role] || roleColors.student
                  }`}
                >
                  {user?.role}
                </span>
              </div>
            </motion.div>
            <Button
              variant="ghost"
              onClick={logout}
              data-testid="logout-btn"
              className="w-full justify-start text-[#9ca3af] hover:text-white hover:bg-[#1e2330] transition-all duration-200"
            >
              <LogOut className="w-4 h-4 mr-2" />
              Sign out
            </Button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-h-screen overflow-hidden">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center justify-between p-4 border-b border-[#1e2330] bg-[#0f1115]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 text-[#9ca3af] hover:text-white transition-colors"
            data-testid="mobile-menu-btn"
          >
            <Menu className="w-6 h-6" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-[#FFBA00] rounded-lg flex items-center justify-center">
              <GraduationCap className="w-4 h-4 text-[#12151a]" />
            </div>
            <span className="font-heading font-bold text-white text-sm">
              SET Chatbot
            </span>
          </div>
          <div className="w-10" /> {/* Spacer for centering */}
        </header>

        {/* Page content */}
        <motion.div 
          key={location.pathname}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex-1 min-h-0 overflow-hidden"
        >
          <Outlet />
        </motion.div>
      </main>
    </div>
  );
}
