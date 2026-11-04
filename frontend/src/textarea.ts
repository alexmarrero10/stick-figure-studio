// Finding and showing a passage inside a <textarea>.

/** Where `find` starts and ends in `text`. Falls back to matching with any run of whitespace
 * (Claude sometimes quotes a passage across a line break with a plain space). null if not found. */
export function findPassage(text: string, find: string): { start: number; end: number } | null {
  const needle = find.trim();
  if (!needle) return null;
  const i = text.indexOf(needle);
  if (i >= 0) return { start: i, end: i + needle.length };
  const escaped = needle.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const m = new RegExp(escaped.join("\\s+")).exec(text);
  return m ? { start: m.index, end: m.index + m[0].length } : null;
}

/** Pixel offset of character `index` from the top of the textarea's content, measured with a hidden
 * copy of the textarea that wraps text the same way. */
function caretTop(ta: HTMLTextAreaElement, index: number): number {
  const style = getComputedStyle(ta);
  const mirror = document.createElement("div");
  for (const p of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "wordSpacing", "tabSize",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"] as const) {
    mirror.style[p] = style[p];
  }
  // clientWidth is the text area inside the border and scrollbar, padding included.
  const inner = ta.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  Object.assign(mirror.style, {
    position: "absolute", visibility: "hidden", top: "0", left: "-9999px", boxSizing: "content-box",
    width: `${inner}px`, whiteSpace: "pre-wrap", overflowWrap: "break-word",
  });
  mirror.textContent = ta.value.slice(0, index);
  const mark = document.createElement("span");
  mark.textContent = "​";
  mirror.appendChild(mark);
  document.body.appendChild(mirror);
  const top = mark.offsetTop;
  mirror.remove();
  return top;
}

/** Scroll the page and the textarea to `find`, then select it so it shows highlighted.
 * Returns false when the text isn't there. */
export function locateText(ta: HTMLTextAreaElement, find: string): boolean {
  const hit = findPassage(ta.value, find);
  if (!hit) return false;
  ta.scrollIntoView({ behavior: "smooth", block: "nearest" });
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(hit.start, hit.end);
  ta.scrollTop = Math.max(0, caretTop(ta, hit.start) - ta.clientHeight / 3);
  return true;
}
