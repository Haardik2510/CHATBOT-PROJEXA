export default function TypingIndicator() {
  return (
    <div className="flex justify-start animate-fadeIn">
      <div className="bg-slate-800 text-white px-4 py-3 rounded-2xl shadow-md flex items-center gap-1">
        <span className="dot"></span>
        <span className="dot"></span>
        <span className="dot"></span>
      </div>
    </div>
  );
}