import type { LabelHTMLAttributes } from "react";

import { cn } from "../../lib/cn";
import { Tooltip, type TooltipContent } from "./tooltip";

export interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
  /** Conteúdo do tooltip de ajuda (descrição + exemplo), mostrado ao passar o mouse ou focar
   *  o próprio texto do rótulo. Opcional — omitido, `Label` renderiza exatamente como antes
   *  (nenhum dos ~40 usos existentes fora do MPC passa isto). */
  tooltip?: TooltipContent;
}

export function Label({ className, tooltip, children, ...props }: LabelProps) {
  return (
    <label className={cn("plaqueta text-xs text-fg-muted", className)} {...props}>
      {tooltip === undefined ? children : <Tooltip content={tooltip}>{children}</Tooltip>}
    </label>
  );
}
