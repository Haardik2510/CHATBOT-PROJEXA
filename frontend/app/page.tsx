"use client";

import { useEffect, useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import ChatInput from "@/components/ChatInput";
import Sidebar from "@/components/Sidebar";
import ChatHeader from "@/components/ChatHeader";

type Message = {
  role: "user" | "assistant";
  content: string;
  status?: "thinking" | "done";
};

type Conversation = {
  id: string;
  title: string;
  messages: Message[];
};

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  // 🔁 Load from localStorage
  useEffect(() => {
    const stored = localStorage.getItem("krmu_chats");
    if (stored) {
      const parsed = JSON.parse(stored);
      setConversations(parsed);
      setActiveId(parsed[0]?.id || null);
    } else {
      createNewChat();
    }
  }, []);

  // 💾 Save to localStorage
  useEffect(() => {
    if (conversations.length > 0) {
      localStorage.setItem("krmu_chats", JSON.stringify(conversations));
    }
  }, [conversations]);

  const createNewChat = () => {
    const newChat: Conversation = {
      id: crypto.randomUUID(),
      title: "New Chat",
      messages: [
        {
          role: "assistant",
          content: "Welcome to KRMU AI Assistant.",
          status: "done",
        },
      ],
    };

    setConversations((prev) => [newChat, ...prev]);
    setActiveId(newChat.id);
  };

  const activeChat = conversations.find((c) => c.id === activeId);

  const handleSend = (text: string) => {
    if (!activeChat) return;

    const updatedChats = conversations.map((chat) => {
      if (chat.id !== activeId) return chat;

      return {
        ...chat,
        title:
          chat.messages.length === 1
            ? text.slice(0, 30)
            : chat.title,
        messages: [
          ...chat.messages,
          { role: "user", content: text, status: "done" },
          { role: "assistant", content: "", status: "thinking" },
        ],
      };
    });

    setConversations(updatedChats);

    // 🔮 Fake AI delay
    setTimeout(() => {
      setConversations((prev) =>
        prev.map((chat) => {
          if (chat.id !== activeId) return chat;

          const updatedMessages = [...chat.messages];
          updatedMessages[updatedMessages.length - 1] = {
            role: "assistant",
            content: `
## KRMU Information

- Established: 2013  
- Location: Gurugram  

\`\`\`python
print("Welcome to KRMU")
\`\`\`
`,
            status: "done",
          };

          return { ...chat, messages: updatedMessages };
        })
      );
    }, 900);
  };

  return (
    <main className="flex h-screen bg-gradient-to-b from-slate-900 to-black text-white">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        setActiveId={setActiveId}
        createNewChat={createNewChat}
      />

      <div className="flex flex-col flex-1">
        {activeChat && (
          <>
          <ChatHeader title={activeChat.title}/>
            <ChatWindow
  key={activeId}
  messages={activeChat.messages}
/>
            <ChatInput onSend={handleSend} />
          </>
        )}
      </div>
    </main>
  );
}