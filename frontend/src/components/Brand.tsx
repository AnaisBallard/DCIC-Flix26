import { Clapperboard } from "lucide-react";

export function Brand({ footer = false }: { footer?: boolean }) {
  return (
    <span className={`brand-mark${footer ? " brand-mark--footer" : ""}`}>
      <Clapperboard aria-hidden="true" size={22} strokeWidth={2.2} />
      <span>DCIC<span className="brand-dash">—</span>FLIX</span>
      <span className="brand-year">26</span>
    </span>
  );
}
