import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage as ChatMessageType } from "../types";
import { BrainIcon, UserIcon } from "./icons";
import { TypingIndicator } from "./TypingIndicator";

interface Props {
  message: ChatMessageType;
  typing: boolean;
}

export function ChatMessage({ message, typing }: Props) {
  const isUser = message.role === "user";
  const showTyping = !isUser && !message.content && typing;

  return (
    <div className={`flex items-start gap-3 animate-fade-slide ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Avatar kind="agent" />}

      <div className={`max-w-[78%] ${isUser ? "flex flex-col items-end" : "min-w-0 flex-1"}`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${
            isUser
              ? "bg-accent text-white rounded-br-sm"
              : "border border-border bg-surface text-text-primary rounded-bl-sm"
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : showTyping ? (
            <TypingIndicator />
          ) : (
            <div className="markdown break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          )}

          {!isUser && typeof message.memoriesUsed === "number" && message.memoriesUsed > 0 && (
            <div className="mt-2 flex justify-end">
              <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">
                {message.memoriesUsed} memóri{message.memoriesUsed === 1 ? "a" : "as"} usadas
              </span>
            </div>
          )}
        </div>
      </div>

      {isUser && <AvatarKindUser />}
    </div>
  );
}

function Avatar({ kind }: { kind: "agent" | "user" }) {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
      <BrainIcon className="h-4 w-4" />
    </div>
  );
}

function AvatarKindUser() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-text-primary">
      <UserIcon className="h-4 w-4" />
    </div>
  );
}