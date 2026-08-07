"use client";

import { useCallback, useEffect, useState } from "react";
import { HardDriveDownload, Pencil, Plus, RefreshCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { VoiceDialog } from "./voice-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ReferenceVoice, type VoiceMeta } from "@/lib/api";

export function VoicesPage() {
  const [voices, setVoices] = useState<ReferenceVoice[]>([]);
  const [meta, setMeta] = useState<VoiceMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ReferenceVoice | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [v, m] = await Promise.all([api.listVoices(), api.voiceMeta()]);
      setVoices(v);
      setMeta(m);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const remove = async (v: ReferenceVoice) => {
    if (!confirm(`Delete "${v.label}"? The clip is removed from the library.`)) return;
    try {
      await api.deleteVoice(v.id);
      toast.success(`Deleted ${v.label}`);
      void reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  const exportSeed = async () => {
    try {
      const r = await api.exportSeed();
      toast.success(
        `Copied ${r.exported} voice(s) into voices_seed/ — commit them so they outlive the volume.`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <div>
          <h1 className="text-lg font-semibold">Reference voices</h1>
          <p className="text-sm text-muted-foreground">
            Clips OmniVoice clones a voice from. A 3–10 s clean recording works
            best.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" size="sm" onClick={reload} disabled={loading}>
            <RefreshCcw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
          <Button variant="outline" size="sm" onClick={exportSeed} title="Copy the library into the repo's voices_seed/">
            <HardDriveDownload className="size-4" />
            Export to repo
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
          >
            <Plus className="size-4" />
            Add voice
          </Button>
        </div>
      </div>

      {meta && (
        <p className="font-mono text-xs text-muted-foreground">{meta.library_root}</p>
      )}

      {voices.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No voices yet. Add one to clone it in every generation.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {voices.map((v) => (
            <VoiceCard
              key={v.id}
              voice={v}
              idealMax={meta?.ideal_max_seconds ?? 10}
              onEdit={() => {
                setEditing(v);
                setDialogOpen(true);
              }}
              onDelete={() => remove(v)}
            />
          ))}
        </div>
      )}

      <VoiceDialog
        // Remount per target so a previous edit never leaks into the next one.
        key={editing?.id ?? "new"}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        voice={editing}
        meta={meta}
        onSaved={reload}
      />
    </div>
  );
}

function VoiceCard({
  voice,
  idealMax,
  onEdit,
  onDelete,
}: {
  voice: ReferenceVoice;
  idealMax: number;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const tooLong = (voice.duration ?? 0) > idealMax;
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-3">
        <div className="min-w-0">
          <CardTitle className="truncate">{voice.label}</CardTitle>
          <p className="truncate font-mono text-xs text-muted-foreground">{voice.id}</p>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button variant="ghost" size="icon" onClick={onEdit}>
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onDelete}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <audio controls preload="none" className="w-full" src={api.voiceAudioUrl(voice.id)} />

        <div className="flex flex-wrap gap-1.5">
          {voice.duration != null && (
            <Badge
              variant="outline"
              className={
                tooLong
                  ? "border-amber-500/50 font-normal text-amber-600 dark:text-amber-400"
                  : "font-normal"
              }
              title={tooLong ? `Longer than the ideal ${idealMax}s — slower to load and clones less cleanly` : undefined}
            >
              {voice.duration.toFixed(1)}s
            </Badge>
          )}
          <Badge variant="outline" className="font-normal">
            {voice.language || "auto"}
          </Badge>
          {voice.used_by > 0 && (
            <Badge variant="secondary" className="font-normal">
              used {voice.used_by}×
            </Badge>
          )}
          {!voice.ref_text && (
            <Badge
              variant="outline"
              className="border-amber-500/50 font-normal text-amber-600 dark:text-amber-400"
              title="Without a transcript the clip is re-transcribed with Whisper on every model load"
            >
              no transcript
            </Badge>
          )}
        </div>

        {voice.description && (
          <p className="text-sm text-muted-foreground">{voice.description}</p>
        )}
        {voice.ref_text && (
          <p className="line-clamp-3 rounded bg-muted/50 p-2 text-xs italic">
            “{voice.ref_text}”
          </p>
        )}
      </CardContent>
    </Card>
  );
}
