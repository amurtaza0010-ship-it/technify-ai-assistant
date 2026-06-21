import styles from "../styles/chat.module.css";
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
    <div
      className={`${styles.messageRow} ${
        isUser ? styles.messageRowUser : styles.messageRowBot
      }`}
    >
      <div
        className={`${styles.messageBubble} ${
          isUser ? styles.userBubble : styles.botBubble
        }`}
      >
        <p className={styles.messageText}>{message.text}</p>
        <span className={styles.messageTime}>
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

export default ChatMessage;
