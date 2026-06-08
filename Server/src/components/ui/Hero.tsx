import React from 'react';
import { motion } from 'framer-motion';
import { Shield, Brain, Zap, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Hero = () => {
  return (
    <section className="relative w-full min-h-screen flex flex-col items-center justify-center px-4 py-24 overflow-hidden bg-[#020617]">
      {/* Background Glows */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-emerald-500/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-500/10 blur-[120px] rounded-full pointer-events-none" />
      
      {/* Grid Pattern */}
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20 pointer-events-none" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:40px_40px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />

      <div className="container relative z-10 max-w-6xl mx-auto text-center">
        {/* Badge */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="inline-flex items-center gap-2 px-3 py-1 mb-8 rounded-full border border-emerald-500/20 bg-emerald-500/5 backdrop-blur-md"
        >
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-medium tracking-wider text-emerald-400 uppercase">
            v1.0.4 WORM • System Active
          </span>
        </motion.div>

        {/* Title */}
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="text-5xl md:text-7xl lg:text-8xl font-black tracking-tighter text-white mb-6"
        >
          SCREEN <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-400">FROG</span>
        </motion.h1>

        {/* Description */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="max-w-2xl mx-auto text-lg md:text-xl text-slate-400 mb-10 leading-relaxed"
        >
          Stealth AI-Powered Industrial Intelligence. 
          A premium two-component ecosystem for high-precision data extraction and haptic feedback.
        </motion.p>

        {/* CTA Buttons */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="flex flex-col sm:flex-row items-center justify-center gap-4"
        >
          <button className="group relative px-8 py-4 bg-emerald-500 text-slate-950 font-bold rounded-xl overflow-hidden transition-all hover:scale-105 active:scale-95">
            <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
            <span className="relative flex items-center gap-2">
              Access Dashboard <ChevronRight className="w-4 h-4" />
            </span>
          </button>
          
          <button className="px-8 py-4 bg-slate-900/50 text-white font-semibold rounded-xl border border-slate-800 backdrop-blur-xl transition-all hover:bg-slate-800 hover:border-slate-700 active:scale-95">
            Documentation
          </button>
        </motion.div>

        {/* Feature Cards */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.4 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-24"
        >
          <div className="group p-8 rounded-2xl border border-white/5 bg-white/[0.02] backdrop-blur-sm text-left transition-all hover:border-emerald-500/30 hover:bg-white/[0.04]">
            <div className="w-12 h-12 rounded-lg bg-emerald-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
              <Shield className="w-6 h-6 text-emerald-400" />
            </div>
            <h3 className="text-xl font-bold text-white mb-3">Stealth Operations</h3>
            <p className="text-slate-500 text-sm leading-relaxed">
              Zero-window architecture with anti-analysis triggers and registry hijacking for ultimate persistence.
            </p>
          </div>

          <div className="group p-8 rounded-2xl border border-white/5 bg-white/[0.02] backdrop-blur-sm text-left transition-all hover:border-cyan-500/30 hover:bg-white/[0.04]">
            <div className="w-12 h-12 rounded-lg bg-cyan-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
              <Brain className="w-6 h-6 text-cyan-400" />
            </div>
            <h3 className="text-xl font-bold text-white mb-3">Hybrid AI Pipeline</h3>
            <p className="text-slate-500 text-sm leading-relaxed">
              Semantic reconstruction using GPT-4o Vision and Claude 3.5 Sonnet for near-100% accuracy.
            </p>
          </div>

          <div className="group p-8 rounded-2xl border border-white/5 bg-white/[0.02] backdrop-blur-sm text-left transition-all hover:border-blue-500/30 hover:bg-white/[0.04]">
            <div className="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
              <Zap className="w-6 h-6 text-blue-400" />
            </div>
            <h3 className="text-xl font-bold text-white mb-3">Haptic Intelligence</h3>
            <p className="text-slate-500 text-sm leading-relaxed">
              Multi-pulse vibration encoding on ESP32 hardware with ultra-low power light sleep mode.
            </p>
          </div>
        </motion.div>
      </div>

      {/* Subtle Bottom Fade */}
      <div className="absolute bottom-0 left-0 right-0 h-64 bg-gradient-to-t from-[#020617] to-transparent pointer-events-none" />
    </section>
  );
};
