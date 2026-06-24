import { useState, useCallback } from "react";

export interface ChatMessageType {
  id: string;
  text: string;
  sender: "user" | "bot";
  timestamp: number;
}

interface UseChatReturn {
  messages: ChatMessageType[];
  isLoading: boolean;
  sendMessage: (text: string) => void;
}

const CHAT_API_URL = import.meta.env.DEV
  ? "/api/v1/chat"
  : (import.meta.env.VITE_TAIA_API_URL || "http://127.0.0.1:8000") + "/api/v1/chat";

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const token = localStorage.getItem("taia_jwt");
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
    return headers;
  }

  headers["x-user-id"] = "STU-0001";
  headers["x-user-role"] = "Student";
  return headers;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessageType[]>([
    {
      id: "welcome-msg",
      text: "Hi there! 👋 How can I assist you today?",
      sender: "bot",
      timestamp: Date.now(),
    },
  ]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const userMessage: ChatMessageType = {
      id: `user-${Date.now()}`,
      text: trimmed,
      sender: "user",
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await fetch(CHAT_API_URL, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ message: trimmed }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to get a response from TAIA.");
      }

      const botMessage: ChatMessageType = {
        id: `bot-${Date.now()}`,
        text: data.response ?? "No response received.",
        sender: "bot",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      const errorText =
        error instanceof Error
          ? error.message
          : "Connection error. Make sure the FastAPI backend is running on port 8000.";

      const botMessage: ChatMessageType = {
        id: `bot-${Date.now()}`,
        text: errorText,
        sender: "bot",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, botMessage]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { messages, isLoading, sendMessage };
}
