"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, type ReferenceVoice } from "@/lib/api";

/** No reference at all — the model invents a voice and drifts over a long script. */
export const VOICE_NONE = "";
/** A path typed by hand, resolved on the box that runs the synthesis. */
export const VOICE_CUSTOM = "__custom__";

/**
 * Voice dropdown with an inline preview button.
 *
 * Hearing the clip before committing GPU-minutes to a long script is the whole
 * reason this is a component and not a bare `<select>`.
 */
export function VoiceSelect({
  value,
  onChange,
  voices,
  includeCustom = true,
}: {
  value: string;
  onChange: (value: string) => void;
  voices: ReferenceVoice[];
  includeCustom?: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  const selected = voices.find((v) => v.id === value) ?? null;

  // Stop playback when the selection changes, otherwise the previous voice
  // keeps talking over the one just picked.
  useEffect(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
  }, [value]);

  const toggle = () => {
    if (!selected) return;
    if (audio.current) {
      audio.current.pause();
      audio.current = null;
      setPlaying(false);
      return;
    }
    const el = new Audio(api.voiceAudioUrl(selected.id));
    el.onended = () => {
      audio.current = null;
      setPlaying(false);
    };
    void el.play();
    audio.current = el;
    setPlaying(true);
  };

  return (
    <div className="flex gap-2">
      <Select value={value} onValueChange={(v) => onChange(v as string)}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={VOICE_NONE}>(none — model invents a voice)</SelectItem>
          {voices.map((v) => (
            <SelectItem key={v.id} value={v.id}>
              {v.label}
              {v.duration ? ` · ${Math.round(v.duration)}s` : ""}
            </SelectItem>
          ))}
          {includeCustom && (
            <SelectItem value={VOICE_CUSTOM}>(custom path on the box…)</SelectItem>
          )}
        </SelectContent>
      </Select>
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={toggle}
        disabled={!selected}
        title={selected ? `Preview ${selected.label}` : "Pick a voice to preview it"}
      >
        {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
      </Button>
    </div>
  );
}
