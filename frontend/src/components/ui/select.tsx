import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

/** Select nativo vestido como poço de instrumento — mesmo tratamento do Input
 *  (DESIGN.md §Shapes/§Don'ts: nenhum componente com cara default). */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-9 w-full rounded-panel border border-hairline bg-well px-2 text-sm text-fg focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Select.displayName = "Select";
