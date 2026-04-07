import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import { Button } from "../components/ui/button";
import { ScrollArea } from "../components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../components/ui/alert-dialog";
import { Users, Trash2, RefreshCw, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";

import { API } from "../lib/api";

const roleColors = {
  student: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  faculty: "bg-green-500/20 text-green-400 border-green-500/30",
  admin: "bg-[#FFBA00]/20 text-[#FFBA00] border-[#FFBA00]/30",
};

export default function UsersView() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUsers = async () => {
    setIsLoading(true);
    try {
      const response = await axios.get(`${API}/admin/users`);
      setUsers(response.data.users);
    } catch (error) {
      console.error("Error fetching users:", error);
      setUsers([]);
      toast.error(error.response?.data?.detail || "Failed to load users");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const updateRole = async (userId, newRole) => {
    try {
      await axios.patch(`${API}/admin/users/${userId}/role?role=${newRole}`);
      toast.success("User role updated");
      fetchUsers();
    } catch (error) {
      console.error("Error updating role:", error);
      toast.error(error.response?.data?.detail || "Failed to update role");
    }
  };

  const deleteUser = async (userId) => {
    try {
      await axios.delete(`${API}/admin/users/${userId}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (error) {
      console.error("Error deleting user:", error);
      toast.error(error.response?.data?.detail || "Failed to delete user");
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const roleCounts = {
    total: users.length,
    students: users.filter((u) => u.role === "student").length,
    faculty: users.filter((u) => u.role === "faculty").length,
    admins: users.filter((u) => u.role === "admin").length,
  };

  const stats = [
    { label: "Total Users", value: roleCounts.total, color: "text-white" },
    { label: "Students", value: roleCounts.students, color: "text-[#b9ceff]" },
    { label: "Faculty", value: roleCounts.faculty, color: "text-emerald-300" },
    { label: "Admins", value: roleCounts.admins, color: "text-[#ffb8bd]" },
  ];

  return (
    <div className="scholar-page p-4 md:p-6 space-y-6">
      {/* Header */}
      <motion.div 
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-[16px] bg-[#0b193c] text-white shadow-[0_14px_26px_rgba(11,25,60,0.16)]">
            <Users className="w-5 h-5" />
          </div>
          <div>
            <p className="section-eyebrow">User Registry</p>
            <h1 className="page-title mt-2">
              Community management
            </h1>
            <p className="mt-2 text-sm text-[#5c6b8d]">
              Manage platform membership, roles, and live academic access.
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchUsers}
          data-testid="refresh-users-btn"
          className="btn-secondary h-11"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="stat-card"
          >
            <span className="text-[#6b7280] text-sm">{stat.label}</span>
            <p className={`text-2xl font-heading font-bold mt-1 ${stat.color}`}>
              {stat.value}
            </p>
          </motion.div>
        ))}
      </div>

      {/* Users table */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="card-surface overflow-hidden"
      >
        <ScrollArea className="h-[500px]">
          <Table>
            <TableHeader>
              <TableRow className="border-[#2a3142] hover:bg-transparent">
                <TableHead className="text-[#9ca3af]">User</TableHead>
                <TableHead className="text-[#9ca3af]">Email</TableHead>
                <TableHead className="text-[#9ca3af]">Role</TableHead>
                <TableHead className="text-[#9ca3af]">Status</TableHead>
                <TableHead className="text-[#9ca3af]">Joined</TableHead>
                <TableHead className="text-[#9ca3af] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    <div className="mx-auto scholar-loader scholar-loader-sm" />
                  </TableCell>
                </TableRow>
              ) : users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-[#6b7280]">
                    No users found.
                  </TableCell>
                </TableRow>
              ) : (
                <AnimatePresence>
                  {users.map((user, i) => {
                    const isCurrentUser = user.id === currentUser?.id;
                    return (
                      <motion.tr
                        key={user.id}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 10 }}
                        transition={{ delay: i * 0.05 }}
                        className="border-[#2a3142] hover:bg-[#1e2330]/50"
                      >
                        <TableCell>
                          <div className="flex items-center gap-3">
                            {user.picture ? (
                              <img
                                src={user.picture}
                                alt={user.name}
                                className="w-9 h-9 rounded-full object-cover"
                              />
                            ) : (
                              <div className="w-9 h-9 bg-[#FFBA00]/10 rounded-full flex items-center justify-center border border-[#FFBA00]/30">
                                <span className="text-sm font-bold text-[#FFBA00]">
                                  {user.name?.charAt(0)?.toUpperCase() || "U"}
                                </span>
                              </div>
                            )}
                            <div>
                              <p className="text-white font-medium">
                                {user.name}
                                {isCurrentUser && (
                                  <span className="ml-2 text-xs text-[#FFBA00]">(You)</span>
                                )}
                              </p>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-[#9ca3af]">{user.email}</TableCell>
                        <TableCell>
                          <Select
                            value={user.role}
                            onValueChange={(value) => updateRole(user.id, value)}
                            disabled={isCurrentUser}
                          >
                            <SelectTrigger
                              data-testid={`role-select-${user.id}`}
                              className={`w-28 h-8 ${roleColors[user.role]} border`}
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-[#1a1e26] border-[#2a3142]">
                              <SelectItem value="student">Student</SelectItem>
                              <SelectItem value="faculty">Faculty</SelectItem>
                              <SelectItem value="admin">Admin</SelectItem>
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              user.is_active
                                ? "bg-green-500/20 text-green-400 border-green-500/30"
                                : "bg-red-500/20 text-red-400 border-red-500/30"
                            }
                          >
                            {user.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-[#9ca3af] text-sm">
                          {formatDate(user.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={isCurrentUser}
                                data-testid={`delete-user-${user.id}`}
                                className="text-[#6b7280] hover:text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                              >
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent className="bg-[#1a1e26] border-[#2a3142]">
                              <AlertDialogHeader>
                                <AlertDialogTitle className="text-white">Delete User</AlertDialogTitle>
                                <AlertDialogDescription className="text-[#9ca3af]">
                                  Are you sure you want to delete <strong>{user.name}</strong>? This action cannot be undone.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel className="bg-[#2a3142] text-white border-[#3f4556] hover:bg-[#3f4556]">
                                  Cancel
                                </AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => deleteUser(user.id)}
                                  className="bg-red-500 text-white hover:bg-red-600"
                                >
                                  Delete
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </TableCell>
                      </motion.tr>
                    );
                  })}
                </AnimatePresence>
              )}
            </TableBody>
          </Table>
        </ScrollArea>
      </motion.div>
    </div>
  );
}
