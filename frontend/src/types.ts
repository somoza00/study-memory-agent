export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  memoriesUsed?: number;
}

export interface StreamEvent {
  type: "token" | "done" | "error";
  content?: string;
  memories_used?: number;
  detail?: string;
}