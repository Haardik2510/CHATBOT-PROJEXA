"use client";

export default function ChatHeader({ title }: { title: string }) {
  return (
    <div className="sticky top-0 z-20 backdrop-blur-xl bg-black/40 border-b border-slate-800">
      <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
        
        <div>
          <h2 className="text-sm font-semibold text-white truncate">
            {title}
          </h2>
          <p className="text-xs text-slate-400">
            KRMU AI • Phi-3 Model
          </p>
        </div>

        <div className="flex items-center gap-3 text-slate-400 text-sm">
          <span className="bg-emerald-500/10 text-emerald-400 px-2 py-1 rounded-full text-xs">
            ● Online
          </span>
        </div>

      </div>
    </div>
  );
}