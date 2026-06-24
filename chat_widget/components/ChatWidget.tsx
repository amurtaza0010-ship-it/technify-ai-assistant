"use client";

import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import ChatMessage from "./ChatMessage";
import { useChat } from "../hooks/useChat";

function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const { messages, isLoading, sendMessage } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isOpen]);

  const handleSend = () => {
    if (!inputValue.trim() || isLoading) return;
    sendMessage(inputValue);
    setInputValue("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSend();
    }
  };

  return (
    <div className="fixed bottom-5 right-5 z-[9999] font-sans">
      {isOpen && (
        <div className="mb-4 flex h-[480px] w-[360px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-widget">
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-slate-800">TAIA Support</p>
              <p className="text-xs text-slate-500">Technify Academic Assistant</p>
            </div>
            <button
              type="button"
              className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-200 hover:text-slate-700"
              onClick={() => setIsOpen(false)}
              aria-label="Close chat"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto bg-white px-3 py-4">
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            {isLoading && (
              <div className="text-xs text-slate-400">TAIA is thinking...</div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-slate-100 bg-white p-3">
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <input
                type="text"
                className="flex-1 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
                placeholder="Type your message..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
              />
              <button
                type="button"
                className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-brand-600 disabled:opacity-50"
                onClick={handleSend}
                disabled={isLoading || !inputValue.trim()}
                aria-label="Send message"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-500 text-xl text-white shadow-widget transition hover:bg-brand-600"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label="Toggle chat widget"
      >
        {isOpen ? "✕" : "💬"}
      </button>
    </div>
  );
}

export default ChatWidget;
