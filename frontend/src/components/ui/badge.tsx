import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const badgeVariants = cva(
  "plaqueta inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 text-[length:var(--fs-label)]",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface-2 text-fg-muted",
        accent: "border-transparent bg-accent-soft text-accent-strong",
        alarm: "border-transparent bg-alarm-soft text-alarm",
        warn: "border-transparent bg-warn-soft text-warn-fg",
        success: "border-transparent bg-success-soft text-success-fg",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
