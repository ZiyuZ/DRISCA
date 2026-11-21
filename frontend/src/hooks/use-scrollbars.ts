import { useEffect } from "react";

export function useScrollbars() {
  useEffect(() => {
    const timers = new Map<HTMLElement, ReturnType<typeof setTimeout>>();
    const reveal = (event: Event) => {
      const element = event.target;
      if (!(element instanceof HTMLElement)) return;
      clearTimeout(timers.get(element));
      element.setAttribute("data-scrolling", "");
      timers.set(element, setTimeout(() => {
        element.removeAttribute("data-scrolling");
        timers.delete(element);
      }, 800));
    };
    document.addEventListener("scroll", reveal, { capture: true, passive: true });
    return () => {
      document.removeEventListener("scroll", reveal, true);
      for (const [element, timer] of timers) {
        clearTimeout(timer);
        element.removeAttribute("data-scrolling");
      }
    };
  }, []);
}
