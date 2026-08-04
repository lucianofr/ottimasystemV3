import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-panel border border-hairline bg-well px-3 text-sm text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-accent",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
