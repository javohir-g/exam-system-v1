import React from 'react';
import { motion } from 'framer-motion';
import { Radio, Battery, Activity, Cpu } from 'lucide-react';
import { cn } from '@/lib/utils';

interface NodeProps {
  id: number;
  status: 'active' | 'idle' | 'offline';
  rssi: number;
  battery: number;
  lastSeen: string;
}

const NodeCard = ({ id, status, rssi, battery, lastSeen }: NodeProps) => {
  const isActive = status === 'active';
  
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      whileInView={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, delay: id * 0.05 }}
      className={cn(
        "relative group p-4 rounded-xl border backdrop-blur-md transition-all duration-500",
        isActive 
          ? "bg-emerald-500/10 border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.1)]" 
          : "bg-white/[0.02] border-white/5 hover:border-white/20"
      )}
    >
      {/* Active Glow */}
      {isActive && (
        <div className="absolute inset-0 bg-emerald-500/20 blur-xl rounded-xl -z-10 animate-pulse" />
      )}

      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-8 h-8 rounded-lg flex items-center justify-center",
            isActive ? "bg-emerald-500/20" : "bg-white/5"
          )}>
            <Cpu className={cn("w-4 h-4", isActive ? "text-emerald-400" : "text-slate-500")} />
          </div>
          <div>
            <h4 className="text-sm font-bold text-white">NODE_{String(id).padStart(2, '0')}</h4>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest">{status}</p>
          </div>
        </div>
        <div className={cn(
          "w-2 h-2 rounded-full",
          status === 'active' ? "bg-emerald-500 animate-pulse" : 
          status === 'idle' ? "bg-amber-500" : "bg-slate-700"
        )} />
      </div>

      <div className="grid grid-cols-2 gap-4 mt-6">
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-slate-500">
            <Radio className="w-3 h-3" />
            <span className="text-[10px] font-bold uppercase">Signal</span>
          </div>
          <p className="text-sm font-mono text-white">{rssi} dBm</p>
        </div>
        <div className="space-y-1 text-right">
          <div className="flex items-center gap-1.5 text-slate-500 justify-end">
            <span className="text-[10px] font-bold uppercase">Battery</span>
            <Battery className="w-3 h-3" />
          </div>
          <p className="text-sm font-mono text-white">{battery}%</p>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-white/5">
        <div className="flex justify-between items-center text-[10px]">
          <span className="text-slate-500 uppercase font-bold tracking-tighter">Last Activity</span>
          <span className="text-slate-400 font-mono">{lastSeen}</span>
        </div>
      </div>
    </motion.div>
  );
};

export const NodeGrid = () => {
  // Mock data for 15 nodes
  const nodes: NodeProps[] = Array.from({ length: 15 }, (_, i) => ({
    id: i + 1,
    status: Math.random() > 0.8 ? 'active' : Math.random() > 0.4 ? 'idle' : 'offline',
    rssi: -40 - Math.floor(Math.random() * 40),
    battery: 15 + Math.floor(Math.random() * 85),
    lastSeen: `${Math.floor(Math.random() * 60)}s ago`
  }));

  return (
    <section className="w-full py-24 bg-[#020617] relative overflow-hidden">
      <div className="container max-w-7xl mx-auto px-4">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
          <div className="space-y-2">
            <h2 className="text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <Activity className="w-8 h-8 text-emerald-500" />
              Fleet Monitoring
            </h2>
            <p className="text-slate-500 max-w-md">
              Real-time telemetry and status tracking for all connected intelligence nodes.
            </p>
          </div>
          <div className="flex gap-4">
             <div className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span className="text-xs font-bold text-white uppercase tracking-wider">4 Active</span>
             </div>
             <div className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-slate-700" />
                <span className="text-xs font-bold text-white uppercase tracking-wider">11 Idle</span>
             </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {nodes.map((node) => (
            <NodeCard key={node.id} {...node} />
          ))}
        </div>
      </div>
    </section>
  );
};
