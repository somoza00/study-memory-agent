import { useState } from "react";

import { BrainIcon, CheckIcon, CloseIcon, PencilIcon } from "./icons";

interface Props {
  topics: string[];
  counts: Record<string, number>;
  activeTopic: string | null;
  onSelect: (topic: string) => void;
  /** Renomeia o tópico no backend; `true` = salvo (fecha o editor). */
  onRename: (topic: string, name: string) => Promise<boolean>;
}

export function TopicsSidebar({ topics, counts, activeTopic, onSelect, onRename }: Props) {
  // Tópico em edição (`null` = nenhum) e o rascunho do nome.
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const startEdit = (topic: string) => {
    setEditing(topic);
    setDraft(topic);
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft("");
  };

  const commitEdit = async (topic: string) => {
    const name = draft.trim();
    // Nome vazio ou igual ao atual: nada a salvar, só fecha o editor.
    if (!name || name === topic) {
      cancelEdit();
      return;
    }
    setSaving(true);
    try {
      const saved = await onRename(topic, name);
      // Em falha o editor fica aberto com o texto digitado, para o usuário
      // corrigir (o motivo aparece no aviso de erro da página).
      if (saved) cancelEdit();
    } finally {
      setSaving(false);
    }
  };

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
            const isEditing = editing === topic;

            return (
              <div key={topic} className="flex items-center gap-1">
                {isEditing ? (
                  <>
                    <input
                      // eslint-disable-next-line jsx-a11y/no-autofocus -- o editor é aberto por ação explícita do usuário
                      autoFocus
                      value={draft}
                      disabled={saving}
                      maxLength={120}
                      aria-label={`Novo nome do tópico ${topic}`}
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void commitEdit(topic);
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          cancelEdit();
                        }
                      }}
                      className="min-w-0 flex-1 rounded-lg border border-accent/60 bg-bg px-3 py-2 text-sm text-text-primary outline-none disabled:opacity-50"
                    />
                    <button
                      type="button"
                      title="Salvar"
                      aria-label={`Salvar novo nome de ${topic}`}
                      disabled={saving}
                      // Evita que o blur do input cancele antes do clique registrar.
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => void commitEdit(topic)}
                      className="shrink-0 rounded p-1 text-accent hover:bg-white/5 disabled:opacity-50"
                    >
                      <CheckIcon />
                    </button>
                    <button
                      type="button"
                      title="Cancelar"
                      aria-label={`Cancelar renomeação de ${topic}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={cancelEdit}
                      className="shrink-0 rounded p-1 text-text-secondary hover:bg-white/5 hover:text-text-primary"
                    >
                      <CloseIcon />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onSelect(topic)}
                      aria-current={active ? "true" : undefined}
                      className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                        active
                          ? "bg-accent/20 text-text-primary"
                          : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
                      }`}
                    >
                      <span className="flex h-2 w-2 shrink-0 rounded-full bg-accent" />
                      <span className="min-w-0 flex-1 truncate font-medium">{topic}</span>
                      <span className="shrink-0 text-xs text-text-secondary">
                        {counts[topic] ?? 0}
                      </span>
                    </button>
                    <button
                      type="button"
                      title="Renomear"
                      aria-label={`Renomear ${topic}`}
                      onClick={() => startEdit(topic)}
                      className="mr-1 shrink-0 rounded p-1 text-text-secondary hover:bg-white/5 hover:text-text-primary"
                    >
                      <PencilIcon />
                    </button>
                  </>
                )}
              </div>
            );
          })
        )}
      </nav>
    </aside>
  );
}
