import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "focus-ring h-10 w-full rounded-md border border-border bg-well px-3 text-sm text-fg transition-colors duration-[var(--duration-fast)] placeholder:text-fg-subtle hover:border-fg-subtle focus-visible:border-accent disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
