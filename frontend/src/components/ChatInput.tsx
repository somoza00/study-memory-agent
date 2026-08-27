import { useEffect, useRef, useState } from "react";
import { SendIcon } from "./icons";

interface Props {
  disabled: boolean;
  onSend: (text: string) => void;
}

export function ChatInput({ disabled, onSend }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  };

  return (
    <form
      className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 focus-within:border-accent"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        disabled={disabled}
        placeholder="Descreva o que estudou ou faça uma pergunta…"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] text-text-primary placeholder:text-text-secondary focus:outline-none disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
        aria-label="Enviar mensagem"
      >
        <SendIcon className="h-4 w-4" />
      </button>
    </form>
  );
}