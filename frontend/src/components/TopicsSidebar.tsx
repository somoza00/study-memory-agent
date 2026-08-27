import { BrainIcon } from "./icons";

interface Props {
  topics: string[];
  counts: Record<string, number>;
  activeTopic: string | null;
  onSelect: (topic: string) => void;
}

export function TopicsSidebar({ topics, counts, activeTopic, onSelect }: Props) {
  return (
    <aside className="flex w-[260px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-4">
        <BrainIcon className="h-6 w-6 text-accent" />
        <span className="truncate text-[15px] font-semibold text-text-primary">Study Memory Agent</span>
      </div>

      <div className="px-4 pb-2 pt-4 text-xs font-medium uppercase tracking-wider text-text-secondary">
        Tópicos
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 pb-4">
        {topics.length === 0 ? (
          <p className="px-3 py-2 text-sm text-text-secondary">Nenhum tópico ainda.</p>
        ) : (
          topics.map((topic) => {
            const active = topic === activeTopic;
            return (
              <button
                key={topic}
                type="button"
                onClick={() => onSelect(topic)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  active
                    ? "bg-accent/20 text-text-primary"
                    : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
                }`}
              >
                <span className="flex h-2 w-2 shrink-0 rounded-full bg-accent" />
                <span className="min-w-0 flex-1 truncate font-medium">{topic}</span>
                <span className="shrink-0 text-xs text-text-secondary">{counts[topic] ?? 0}</span>
              </button>
            );
          })
        )}
      </nav>
    </aside>
  );
}