export function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 rounded-full bg-text-secondary animate-typing-dot"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  );
}