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

function getMockBotResponse(userText: string): string {
  const responses = [
    "Thanks for your message! How can I help you today?",
    "I understand. Let me look into that for you.",
    "That's a great question! Here's what I can tell you...",
    "I'm just a demo bot right now, but soon I'll be connected to a real backend.",
  ];
  return responses[Math.floor(Math.random() * responses.length)];
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

  const sendMessage = useCallback((text: string) => {
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

    setTimeout(() => {
      const botMessage: ChatMessageType = {
        id: `bot-${Date.now()}`,
        text: getMockBotResponse(trimmed),
        sender: "bot",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, botMessage]);
      setIsLoading(false);
    }, 800);
  }, []);

  return { messages, isLoading, sendMessage };
}