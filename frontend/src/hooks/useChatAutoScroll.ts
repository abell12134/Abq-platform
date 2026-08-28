import { useEffect, useRef } from "react";

const NEAR_BOTTOM_PX = 120;

/** Keep chat pinned to bottom while streaming unless the user scrolls up. */
export function useChatAutoScroll(enabled: boolean, scrollKey: number) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !enabled) return;

    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      stickToBottomRef.current = distance <= NEAR_BOTTOM_PX;
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !stickToBottomRef.current) return;
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [enabled, scrollKey]);

  return containerRef;
}
