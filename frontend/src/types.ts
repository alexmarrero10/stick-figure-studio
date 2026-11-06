export interface Idea {
  id: number;
  project_id: number | null;
  title: string;
  hook: string;
  why_it_works: string;
  category: string;
  era: string;
  documentation: string;
  source: string;
  saved: number;
  format: VideoFormat;
}

export type VideoFormat = "story" | "topic" | "list";

export const FORMAT_LABELS: Record<VideoFormat, string> = {
  story: "One story",
  topic: "Topic explained",
  list: "Countdown list",
};

export interface Status {
  research: boolean;
  script: boolean;
  script_words: number;
  beats: number;
  beats_stale: boolean;
  voice: boolean;
  voice_stale: boolean;
  prompts: number;
  prompts_missing: number;
  images: number;
  images_filled: number; // slots with a picture (extras not counted)
  images_complete: boolean;
  shots: number;
  publish: boolean;
  short: boolean;
  site: boolean;
}

export interface Project {
  id: number;
  slug: string;
  title: string;
  idea_id: number | null;
  idea?: Idea | null;
  format: VideoFormat;
  archived: number;
  status: Status;
  created_at: string;
  updated_at: string;
}

export interface ScriptVersion {
  id: number;
  project_id: number;
  text: string;
  source: string;
  instruction: string | null;
  word_count: number;
  created_at: string;
}

export interface Beat {
  id: number;
  idx: number;
  word_start: number;
  word_end: number;
  text: string;
  est_seconds: number;
  start?: number;
  end?: number;
  script_version_id: number;
}

export interface Edit {
  find: string;
  replace: string;
  reason: string;
  ok: boolean;
  error: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  edits: Edit[] | null;
}

export interface Settings {
  config: Record<string, Record<string, unknown>>;
  keys: Record<string, string | null>;
}
