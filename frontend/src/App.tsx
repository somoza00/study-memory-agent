import { ChatPanel } from "./components/ChatPanel";
import { MemoryForm } from "./components/MemoryForm";
import { MemoryList } from "./components/MemoryList";

function App() {
  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif", maxWidth: 720, margin: "0 auto" }}>
      <h1>Study Memory Agent</h1>
      <p>Scaffold pronto — interface de chat e memórias em construção.</p>
      <MemoryForm />
      <MemoryList />
      <ChatPanel />
    </main>
  );
}

export default App;
