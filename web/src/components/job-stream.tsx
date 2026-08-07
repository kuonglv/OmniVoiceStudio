"use client";

import { useEffect, useRef, useState } from "react";
import { Ban, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api, wsUrl, type Job, type JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

interface LogLine {
  stream: string;
  line: string;
}

const TONE: Record<JobStatus, string> = {
  pending: "text-muted-foreground",
  running: "text-blue-600 dark:text-blue-400",
  succeeded: "text-emerald-600 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
  cancelled: "text-amber-600 dark:text-amber-400",
};

/**
 * Live console for one job.
 *
 * The socket replays the job's whole history on connect, so a reload mid-run —
 * or opening a finished job from the Jobs page — shows the same thing as
 * having watched it from the start.
 */
export function JobStream({
  jobId,
  onFinished,
}: {
  jobId: string;
  onFinished?: (status: JobStatus) => void;
}) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [status, setStatus] = useState<JobStatus>("pending");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const finished = useRef(false);

  useEffect(() => {
    setLogs([]);
    setStatus("pending");
    setProgress(0);
    setError(null);
    finished.current = false;

    const ws = new WebSocket(wsUrl(`/api/jobs/ws/${jobId}`));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      switch (msg.type) {
        case "hello": {
          const job = msg.job as Job;
          setStatus(job.status);
          setProgress(job.progress);
          break;
        }
        case "log":
          setLogs((prev) => [...prev, { stream: msg.stream, line: msg.line }]);
          break;
        case "status":
          setStatus(msg.status);
          if (typeof msg.progress === "number") setProgress(msg.progress);
          if (msg.error) setError(msg.error);
          if (["succeeded", "failed", "cancelled"].includes(msg.status) && !finished.current) {
            finished.current = true;
            onFinished?.(msg.status);
          }
          break;
        case "error":
          setError(msg.error);
          break;
      }
    };
    ws.onerror = () => setError("Lost the connection to the backend.");
    return () => ws.close();
    // onFinished is intentionally not a dependency: a parent that redefines it
    // each render would otherwise tear down and re-open the socket every time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // Follow the tail, but stop fighting the user the moment they scroll up.
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [logs]);

  const running = status === "pending" || status === "running";

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className={cn("font-normal", TONE[status])}>
          {running && <Loader2 className="mr-1 size-3 animate-spin" />}
          {status}
        </Badge>
        <span className="font-mono text-xs text-muted-foreground">{jobId.slice(0, 8)}</span>
        {running && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={async () => {
              const r = await api.cancelJob(jobId);
              toast.info(r.note);
            }}
          >
            <Ban className="size-4" />
            Cancel
          </Button>
        )}
      </div>

      {running && <Progress value={progress * 100} />}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="h-72 overflow-y-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed"
      >
        {logs.length === 0 ? (
          <p className="text-muted-foreground">Waiting for output…</p>
        ) : (
          logs.map((l, i) => (
            <div
              key={i}
              className={cn(
                "whitespace-pre-wrap break-words",
                l.stream === "stderr" && "text-red-600 dark:text-red-400",
              )}
            >
              {l.line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
