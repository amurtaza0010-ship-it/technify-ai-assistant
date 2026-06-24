import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessageType } from "../hooks/useChat";

interface ChatMessageProps {
  message: ChatMessageType;
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.sender === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 ${
          isUser
            ? "rounded-br-md bg-brand-500 text-white"
            : "rounded-bl-md border border-slate-100 bg-slate-50 text-slate-800"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.text}</p>
        ) : (
          <div className="markdown-content text-sm leading-relaxed text-slate-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
          </div>
        )}
        <span
          className={`mt-1 block text-[10px] ${
            isUser ? "text-emerald-100" : "text-slate-400"
          }`}
        >
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

export default ChatMessage;
