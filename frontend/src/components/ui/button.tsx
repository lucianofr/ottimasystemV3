import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const buttonVariants = cva(
  "focus-ring inline-flex items-center justify-center gap-2 rounded-pill border text-sm font-semibold transition-all duration-[var(--duration-fast)] ease-[var(--ease-out)] active:translate-y-0 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "border-transparent bg-accent text-white shadow-sm hover:-translate-y-px hover:bg-accent-strong hover:shadow-[var(--shadow-glow-accent)]",
        outline:
          "border-border bg-surface text-fg shadow-sm hover:-translate-y-px hover:border-accent hover:text-accent hover:shadow-md",
        ghost: "border-transparent bg-transparent text-fg-muted hover:bg-surface-2 hover:text-fg",
        destructive:
          "border-transparent bg-alarm text-white shadow-sm hover:-translate-y-px hover:shadow-md",
      },
      size: {
        default: "h-9 px-5",
        sm: "h-8 px-3.5 text-xs",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";
