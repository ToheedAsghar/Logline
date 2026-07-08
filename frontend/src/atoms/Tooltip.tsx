import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";
import { cn } from "@/common/utils";

export type TooltipSide = "top" | "bottom" | "left" | "right";

export interface TooltipProps {
  content: ReactNode;
  /** A single focusable/hoverable element (button, icon-button, etc.). */
  children: ReactElement;
  side?: TooltipSide;
  className?: string;
}

const SIDE_POSITION: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
};

/**
 * Not present in the handoff — every hint there rides on the native
 * `title=""` attribute (see the sidebar's collapsed nav icons, the refresh
 * button, the calendar prev/next arrows). Native titles aren't stylable and
 * are slow/inconsistent to show, so this gives the same "one-line hint"
 * job a component matching the surface/popover styling used elsewhere
 * (the calendar dropdown, the source-picker menu): surface bg, border2
 * border, floating shadow.
 */
export function Tooltip({ content, children, side = "top", className }: TooltipProps) {
  const id = useId();
  if (!isValidElement(children)) return children;

  const trigger = cloneElement(children as ReactElement<Record<string, unknown>>, {
    "aria-describedby": id,
  });

  return (
    <span className="group relative inline-flex">
      {trigger}
      <span
        role="tooltip"
        id={id}
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-sm border border-border-2 bg-surface",
          "px-2.5 py-1.5 font-sans text-xs text-text shadow-elevated opacity-0 scale-95",
          "transition-[opacity,transform] duration-100 ease-out",
          "group-hover:opacity-100 group-hover:scale-100 group-focus-within:opacity-100 group-focus-within:scale-100",
          SIDE_POSITION[side],
          className,
        )}
      >
        {content}
      </span>
    </span>
  );
}
