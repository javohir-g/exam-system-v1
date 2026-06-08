import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Terminal, Eye, Brain, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LogEntry {
  id: string;
  timestamp: string;
  source: 'vision' | 'logic' | 'system';
  message: string;
  status: 'processing' | 'success' | 'error';
}

const SourceBadge = ({ source }: { source: LogEntry['source'] }) => {
  const styles = {
    vision: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    logic: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    system: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  };

  const icons = {
    vision: <Eye className="w-3 h-3" />,
    logic: <Brain className="w-3 h-3" />,
    system: <Terminal className="w-3 h-3" />,
  };

  return (
    <div className={cn("flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", styles[source])}>
      {icons[source]}
      {source}
    </div>
  );
};

export const AIReasoningLog = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    const mockLogs: LogEntry[] = [
      { id: '1', timestamp: '22:14:05', source: 'system', message: 'Incoming payload from NODE_04 (Screenshot: 1240x2800)', status: 'success' },
      { id: '2', timestamp: '22:14:06', source: 'vision', message: 'GPT-4o scanning layout structures... Detected 4 interactive elements.', status: 'processing' },
      { id: '3', timestamp: '22:14:08', source: 'vision', message: 'Reconstructing Digital Twin. taskType: "matching_drag_drop"', status: 'success' },
      { id: '4', timestamp: '22:14:09', source: 'logic', message: 'Claude 3.5 analyzing semantic relationships and solving logic puzzle...', status: 'processing' },
      { id: '5', timestamp: '22:14:11', source: 'logic', message: 'Match found: [A-4, B-1, C-2, D-3]. Confidence: 99.8%', status: 'success' },
      { id: '6', timestamp: '22:14:12', source: 'system', message: 'Encoding haptic sequence. Dispatching to ESP32: [4-PULSE-BURST]', status: 'success' },
    ];

    // Simulate real-time logging
    let i = 0;
    const interval = setInterval(() => {
      if (i < mockLogs.length) {
        setLogs(prev => [mockLogs[i], ...prev].slice(0, 8));
        i++;
      } else {
        clearInterval(interval);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, []);

  return (
    <section className="w-full py-12 bg-[#020617]">
      <div className="container max-w-7xl mx-auto px-4">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          
          {/* Header Info */}
          <div className="lg:col-span-4 space-y-6">
            <div className="p-8 rounded-3xl bg-gradient-to-br from-emerald-500/10 to-transparent border border-emerald-500/20 backdrop-blur-xl">
              <div className="w-12 h-12 rounded-2xl bg-emerald-500/20 flex items-center justify-center mb-6">
                <Brain className="w-6 h-6 text-emerald-500" />
              </div>
              <h2 className="text-3xl font-black text-white mb-4 tracking-tight">Intelligence Pipeline</h2>
              <p className="text-slate-400 text-sm leading-relaxed mb-6">
                Watch the multi-model semantic reconstruction in real-time. GPT-4o visualizes the structure, while Claude 3.5 provides the logical resolution.
              </p>
              <div className="space-y-3">
                <div className="flex items-center gap-3 text-xs font-bold text-slate-500 uppercase tracking-widest">
                  <div className="w-1 h-1 rounded-full bg-emerald-500" />
                  Avg Latency: 4.2s
                </div>
                <div className="flex items-center gap-3 text-xs font-bold text-slate-500 uppercase tracking-widest">
                  <div className="w-1 h-1 rounded-full bg-cyan-500" />
                  Accuracy: 99.4%
                </div>
              </div>
            </div>
          </div>

          {/* Terminal Window */}
          <div className="lg:col-span-8">
            <div className="relative rounded-2xl border border-white/5 bg-black/40 backdrop-blur-md overflow-hidden shadow-2xl">
              {/* Terminal Header */}
              <div className="flex items-center justify-between px-4 py-3 bg-white/5 border-bottom border-white/5">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500/40" />
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/40" />
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/40" />
                </div>
                <div className="text-[10px] font-mono text-slate-500 uppercase tracking-widest font-bold">
                  Reasoning_Core_v4.log
                </div>
                <div className="w-12" /> {/* Spacer */}
              </div>

              {/* Log List */}
              <div className="p-6 font-mono text-sm h-[450px] overflow-hidden flex flex-col gap-4">
                <AnimatePresence initial={false}>
                  {logs.map((log) => (
                    <motion.div
                      key={log.id}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, scale: 0.95 }}
                      className="group flex gap-4 items-start"
                    >
                      <span className="text-slate-600 shrink-0 text-xs mt-1">[{log.timestamp}]</span>
                      <div className="flex flex-col gap-2 w-full">
                        <div className="flex items-center gap-3">
                          <SourceBadge source={log.source} />
                          {log.status === 'processing' && (
                            <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />
                          )}
                          {log.status === 'success' && (
                            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                          )}
                        </div>
                        <p className={cn(
                          "text-sm leading-relaxed",
                          log.status === 'processing' ? "text-slate-400 italic" : "text-slate-200"
                        )}>
                          {log.message}
                        </p>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
                
                {/* Empty State / Bottom Glow */}
                {logs.length === 0 && (
                  <div className="flex items-center justify-center h-full text-slate-600 animate-pulse uppercase text-xs font-bold tracking-widest">
                    Awaiting Signal...
                  </div>
                )}
              </div>

              {/* Scanline Effect */}
              <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.1)_50%),linear-gradient(90deg,rgba(255,0,0,0.02),rgba(0,255,0,0.01),rgba(0,0,255,0.02))] bg-[length:100%_4px,3px_100%]" />
            </div>
          </div>

        </div>
      </div>
    </section>
  );
};
