// Phrases that make narration sound machine-written. The script prompt (backend/pipeline/script.py,
// "SOUND LIKE A REAL PERSON TELLING IT") tells Claude to avoid the same ones; this catches any that slip through.
const PHRASES = [
  "little did they know",
  "in a world where",
  "a testament to",
  "delve",
  "tapestry",
  "it's worth noting",
  "buckle up",
  "fast forward to",
  "the rest is history",
  "sent shockwaves",
  "forever changed",
  "a chilling reminder",
  "stood the test of time",
  "against all odds",
  "will shock you",
  "here's the kicker",
  "plot twist",
];

const PATTERNS: { label: string; re: RegExp }[] = [
  ...PHRASES.map((p) => ({ label: p, re: new RegExp(`\\b${p.replace(/'/g, "['’]")}`, "gi") })),
  { label: "It wasn't X. It was Y.", re: /\b(it|this|that) (wasn't|was not|isn't|is not) [^.!?]{1,60}[.!?]\s+(it|this|that) (was|is)\b/gi },
];

export interface Tell {
  label: string;
  count: number;
}

export function findTells(text: string): Tell[] {
  return PATTERNS.map(({ label, re }) => ({ label, count: text.match(re)?.length ?? 0 })).filter((t) => t.count > 0);
}
