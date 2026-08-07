"use client";

import { useEffect, useState } from "react";
import { Download, FileArchive } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type OutputFile, type OutputSet } from "@/lib/api";

function human(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * What a job produced: every WAV playable in place, everything downloadable.
 *
 * Audio is streamed from the pod rather than downloaded first, so a 40-minute
 * WAV can be auditioned by seeking into the middle of it.
 */
export function OutputPanel({ jobId }: { jobId: string }) {
  const [set, setSet] = useState<OutputSet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getOutput(jobId)
      .then(setSet)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [jobId]);

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!set) return null;

  const audio = set.files.filter((f) => f.kind === "audio");
  const others = set.files.filter((f) => f.kind !== "audio");

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">Output</span>
        <Badge variant="outline" className="font-normal">
          {human(set.total_size)}
        </Badge>
        <Button
          render={<a href={api.zipUrl(jobId)} />}
          variant="outline"
          size="sm"
          className="ml-auto"
        >
          <FileArchive className="size-4" />
          Download all
        </Button>
      </div>

      {audio.length === 0 && (
        <p className="text-sm text-muted-foreground">No audio was produced.</p>
      )}

      <div className="space-y-3">
        {audio.map((f) => (
          <AudioRow key={f.name} jobId={jobId} file={f} />
        ))}
      </div>

      {others.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {others.map((f) => (
            <Button
              key={f.name}
              render={<a href={api.fileUrl(jobId, f.name, true)} />}
              variant="ghost"
              size="sm"
            >
              <Download className="size-3.5" />
              <span className="font-mono text-xs">{f.name}</span>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

function AudioRow({ jobId, file }: { jobId: string; file: OutputFile }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="truncate font-mono text-xs">{file.name}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {human(file.size)}
        </span>
        <Button
          render={<a href={api.fileUrl(jobId, file.name, true)} />}
          variant="ghost"
          size="sm"
          className="ml-auto shrink-0"
        >
          <Download className="size-3.5" />
        </Button>
      </div>
      <audio controls preload="none" className="w-full" src={api.fileUrl(jobId, file.name)} />
    </div>
  );
}
