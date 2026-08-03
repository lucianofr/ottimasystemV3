import type { HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

/** Chapa: superfície elevada por tom + linha 1px, nunca sombra (DESIGN.md §Elevation). */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-panel border border-hairline bg-panel", className)} {...props} />
  );
}
