"use client";

import { useState } from "react";

type Props = {
  conversations: any[];
  activeId: string | null;
  setActiveId: (id: string) => void;
  createNewChat: () => void;
};

export default function Sidebar({
  conversations,
  activeId,
  setActiveId,
  createNewChat,
}: Props) {
  const [open, setOpen] = useState(true);

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-sm z-30 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div
        className={`fixed md:relative z-40 h-full glass border-r border-slate-800 transition-all duration-300
        ${open ? "w-64 translate-x-0" : "-translate-x-full md:translate-x-0 md:w-16"}`}
      >
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          {open && (
            <button
              onClick={createNewChat}
              className="bg-indigo-600 hover:bg-indigo-500 active:scale-95 transition-all px-3 py-2 rounded-lg text-sm"
            >
              + New Chat
            </button>
          )}

          <button
            onClick={() => setOpen(!open)}
            className="text-slate-400 hover:text-white transition"
          >
            ☰
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {conversations.map((chat) => (
            <div
              key={chat.id}
              onClick={() => setActiveId(chat.id)}
              className={`p-3 rounded-xl cursor-pointer text-sm transition-all duration-200 truncate
                ${
                  chat.id === activeId
                    ? "bg-slate-700 shadow-lg shadow-indigo-500/10"
                    : "hover:bg-slate-800 hover:translate-x-1"
                }`}
            >
              {open ? chat.title : "💬"}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}