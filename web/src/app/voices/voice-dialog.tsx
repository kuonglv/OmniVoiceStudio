"use client";

import { useRef, useState } from "react";
import { FileAudio, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, type ReferenceVoice, type VoiceMeta } from "@/lib/api";

/**
 * Add or edit one reference voice.
 *
 * `voice === null` is add mode, where a clip must be uploaded. In edit mode the
 * clip already exists and the file field becomes an optional "replace it" —
 * replacing keeps the id, so anything already pointing at this voice picks up
 * the new recording without being reconfigured.
 */
export function VoiceDialog({
  open,
  onOpenChange,
  voice,
  meta,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  voice: ReferenceVoice | null;
  meta: VoiceMeta | null;
  onSaved: () => void;
}) {
  const editing = voice !== null;
  const defaultLanguage = meta?.default_language ?? "en";
  const idealMax = meta?.ideal_max_seconds ?? 10;
  const accept = (meta?.audio_exts ?? [".wav", ".mp3"]).join(",");

  const [label, setLabel] = useState(voice?.label ?? "");
  const [voiceId, setVoiceId] = useState(voice?.id ?? "");
  const [description, setDescription] = useState(voice?.description ?? "");
  const [refText, setRefText] = useState(voice?.ref_text ?? "");
  const [language, setLanguage] = useState(voice?.language ?? defaultLanguage);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim()) {
      toast.error("A label is required.");
      return;
    }
    if (!editing && !file) {
      toast.error("Choose an audio clip to upload.");
      return;
    }

    setBusy(true);
    try {
      if (!editing) {
        const form = new FormData();
        form.append("file", file!);
        form.append("label", label.trim());
        form.append("description", description);
        form.append("ref_text", refText);
        form.append("language", language);
        form.append("voice_id", voiceId.trim());
        await api.createVoice(form);
        toast.success(`Added ${label}`);
      } else {
        // Metadata first, then the two operations that can move files. If a
        // rename fails the metadata edit is already safely saved.
        await api.updateVoice(voice.id, {
          label: label.trim(),
          description,
          ref_text: refText,
          language,
        });
        if (file) {
          const form = new FormData();
          form.append("file", file);
          await api.replaceClip(voice.id, form);
        }
        if (voiceId.trim() && voiceId.trim() !== voice.id) {
          await api.renameVoice(voice.id, { new_id: voiceId.trim() });
          toast.info(
            `Renamed to "${voiceId.trim()}" — anything referring to the old id must be updated.`,
          );
        }
        toast.success(`Saved ${label}`);
      }
      onSaved();
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${voice.label}` : "Add a voice"}</DialogTitle>
            <DialogDescription>
              A clean {idealMax}-second-or-shorter clip in the same language as
              the scripts clones best.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-1.5">
            <Label htmlFor="clip">{editing ? "Replace clip (optional)" : "Clip"}</Label>
            <input
              ref={fileInput}
              id="clip"
              type="file"
              accept={accept}
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start font-normal"
              onClick={() => fileInput.current?.click()}
            >
              <FileAudio className="size-4" />
              {file ? file.name : editing ? voice.audio : "Choose an audio file…"}
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="The Lord Chosen"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="vid">Id</Label>
              <Input
                id="vid"
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
                placeholder="derived from the label"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="lang">Language</Label>
            <Input
              id="lang"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder={defaultLanguage}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="reftext">Transcript of the clip</Label>
            <Textarea
              id="reftext"
              rows={3}
              value={refText}
              onChange={(e) => setRefText(e.target.value)}
              placeholder="Exactly what the clip says, word for word."
            />
            <p className="text-xs text-muted-foreground">
              Blank means Whisper re-transcribes the clip on every model load —
              slower, and a wrong guess distorts the clone.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="desc">Notes</Label>
            <Input
              id="desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Where it came from, what it is for"
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 className="size-4 animate-spin" />}
              {editing ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
