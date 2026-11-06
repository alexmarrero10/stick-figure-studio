import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

/* Minimal typing for the YouTube IFrame Player API. */
interface YTPlayer {
  seekTo(s: number, allowSeekAhead: boolean): void;
  playVideo(): void;
  getCurrentTime(): number;
  destroy(): void;
}
declare global {
  interface Window {
    YT?: { Player: new (el: HTMLElement, opts: object) => YTPlayer };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiReady: Promise<void> | null = null;
function loadApi(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve();
  if (!apiReady) {
    apiReady = new Promise((resolve) => {
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        prev?.();
        resolve();
      };
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(s);
    });
  }
  return apiReady;
}

export interface PlayerHandle {
  seek(s: number): void;
  time(): number | null;
}

/** The YouTube player. The chat uses seek() for timestamp links and time() to know where the viewer is. */
export const Player = forwardRef<PlayerHandle, { videoId: string; start: number }>(function Player(
  { videoId, start },
  ref,
) {
  const box = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);

  useEffect(() => {
    let alive = true;
    loadApi().then(() => {
      if (!alive || !box.current || !window.YT) return;
      const el = document.createElement("div");
      box.current.replaceChildren(el);
      player.current = new window.YT.Player(el, {
        videoId,
        playerVars: { start: Math.floor(start), rel: 0, modestbranding: 1, playsinline: 1 },
      });
    });
    return () => {
      alive = false;
      player.current?.destroy();
      player.current = null;
    };
  }, [videoId]);

  useImperativeHandle(ref, () => ({
    seek(s: number) {
      if (!player.current) return;
      player.current.seekTo(s, true);
      player.current.playVideo();
      // On phones the chat sits below the video: bring the player back into view.
      const r = box.current?.getBoundingClientRect();
      if (r && (r.bottom < 60 || r.top > window.innerHeight)) box.current?.scrollIntoView({ behavior: "smooth" });
    },
    time() {
      try {
        return player.current ? player.current.getCurrentTime() : null;
      } catch {
        return null;
      }
    },
  }));

  return <div className="player" ref={box} />;
});
