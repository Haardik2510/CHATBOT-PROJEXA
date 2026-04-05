import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  MessageSquare,
  FileText,
  Users,
  TrendingUp,
  Clock,
  Mic,
  RefreshCw,
} from "lucide-react";
import { Button } from "../components/ui/button";

import { API } from "../lib/api";

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[#1a1e26] border border-[#2a3142] rounded-lg px-3 py-2 shadow-xl">
        <p className="text-white font-medium text-sm">{label}</p>
        {payload.map((entry, index) => (
          <p key={index} className="text-sm text-[#9ca3af]">
            {entry.name}: <span className="text-[#FFBA00] font-mono">{entry.value}</span>
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function AnalyticsView() {
  const [overview, setOverview] = useState(null);
  const [dailyStats, setDailyStats] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchAnalytics = async () => {
    setIsLoading(true);
    try {
      const [overviewRes, dailyRes] = await Promise.all([
        axios.get(`${API}/analytics/overview`),
        axios.get(`${API}/analytics/daily?days=7`),
      ]);
      setOverview(overviewRes.data);
      setDailyStats(dailyRes.data.stats);
    } catch (error) {
      console.error("Error fetching analytics:", error);
      setOverview({
        total_queries: 0,
        total_documents: 0,
        total_users: 0,
        queries_today: 0,
        avg_response_time_ms: 0,
        voice_query_percentage: 0,
      });
      setDailyStats([]);
      toast.error(error.response?.data?.detail || "Failed to load analytics");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="w-10 h-10 border-4 border-[#FFBA00] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const statCards = [
    { label: "Total Queries", value: overview?.total_queries || 0, icon: MessageSquare, color: "text-blue-400", bg: "bg-blue-500/10" },
    { label: "Total Documents", value: overview?.total_documents || 0, icon: FileText, color: "text-green-400", bg: "bg-green-500/10" },
    { label: "Total Users", value: overview?.total_users || 0, icon: Users, color: "text-purple-400", bg: "bg-purple-500/10" },
    { label: "Queries Today", value: overview?.queries_today || 0, icon: TrendingUp, color: "text-[#FFBA00]", bg: "bg-[#FFBA00]/10" },
    { label: "Avg Response Time", value: `${Math.round(overview?.avg_response_time_ms || 0)}ms`, icon: Clock, color: "text-cyan-400", bg: "bg-cyan-500/10" },
    { label: "Voice Queries", value: `${Math.round(overview?.voice_query_percentage || 0)}%`, icon: Mic, color: "text-pink-400", bg: "bg-pink-500/10" },
  ];

  return (
    <div className="p-4 md:p-6 space-y-6">
      {/* Header */}
      <motion.div 
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-heading font-bold text-white">
            Analytics Dashboard
          </h1>
          <p className="text-sm text-[#6b7280] mt-1">
            Monitor chatbot usage and performance
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchAnalytics}
          data-testid="refresh-analytics-btn"
          className="text-[#9ca3af] hover:text-white hover:bg-[#1e2330]"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </motion.div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {statCards.map((stat, i) => (
          <motion.div 
            key={stat.label} 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="stat-card"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[#6b7280] text-xs">{stat.label}</span>
              <div className={`w-8 h-8 ${stat.bg} rounded-lg flex items-center justify-center`}>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </div>
            </div>
            <p className="text-2xl font-heading font-bold text-white">{stat.value}</p>
          </motion.div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Query Trend */}
        <motion.div 
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.4 }}
          className="card-surface p-6"
        >
          <h3 className="text-lg font-heading font-semibold text-white mb-4">
            Query Trend (Last 7 Days)
          </h3>
          <div className="h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyStats}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a3142" />
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  fontSize={12}
                  tickFormatter={(value) => {
                    const date = new Date(value);
                    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                  }}
                />
                <YAxis stroke="#6b7280" fontSize={12} />
                <Tooltip content={<CustomTooltip />} />
                <Line
                  type="monotone"
                  dataKey="query_count"
                  name="Queries"
                  stroke="#FFBA00"
                  strokeWidth={3}
                  dot={{ fill: "#FFBA00", strokeWidth: 0, r: 4 }}
                  activeDot={{ r: 6, fill: "#FFBA00" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        {/* Users Trend */}
        <motion.div 
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.5 }}
          className="card-surface p-6"
        >
          <h3 className="text-lg font-heading font-semibold text-white mb-4">
            Active Users (Last 7 Days)
          </h3>
          <div className="h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dailyStats}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a3142" />
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  fontSize={12}
                  tickFormatter={(value) => {
                    const date = new Date(value);
                    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                  }}
                />
                <YAxis stroke="#6b7280" fontSize={12} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="unique_users" name="Users" fill="#FFBA00" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        {/* Response Time */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="card-surface p-6 md:col-span-2"
        >
          <h3 className="text-lg font-heading font-semibold text-white mb-4">
            Average Response Time (Last 7 Days)
          </h3>
          <div className="h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyStats}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a3142" />
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  fontSize={12}
                  tickFormatter={(value) => {
                    const date = new Date(value);
                    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                  }}
                />
                <YAxis stroke="#6b7280" fontSize={12} tickFormatter={(value) => `${value}ms`} />
                <Tooltip content={<CustomTooltip />} />
                <Line
                  type="monotone"
                  dataKey="avg_response_time"
                  name="Avg Response Time (ms)"
                  stroke="#22c55e"
                  strokeWidth={3}
                  dot={{ fill: "#22c55e", strokeWidth: 0, r: 4 }}
                  activeDot={{ r: 6, fill: "#22c55e" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
