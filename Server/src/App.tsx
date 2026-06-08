import { Hero } from './components/ui/Hero';
import { NodeGrid } from './components/ui/NodeGrid';
import { AIReasoningLog } from './components/ui/AIReasoningLog';

function App() {
  return (
    <main className="relative min-h-screen flex flex-col bg-[#020617]">
      <Hero />
      <NodeGrid />
      <AIReasoningLog />
      {/* Components will be stacked here */}
    </main>
  )
}

export default App
