import type { LabelHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("plaqueta text-xs text-fg-muted", className)} {...props} />;
}
