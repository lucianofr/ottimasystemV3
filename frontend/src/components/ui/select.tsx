import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "focus-ring h-10 w-full rounded-md border border-border bg-well px-3 text-sm text-fg transition-colors duration-[var(--duration-fast)] hover:border-fg-subtle focus-visible:border-accent disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Select.displayName = "Select";
