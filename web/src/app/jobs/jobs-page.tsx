"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { JobStream } from "@/components/job-stream";
import { OutputPanel } from "@/components/output-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api, type Job, type JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const TONE: Record<JobStatus, string> = {
  pending: "text-muted-foreground",
  running: "text-blue-600 dark:text-blue-400",
  succeeded: "text-emerald-600 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
  cancelled: "text-amber-600 dark:text-amber-400",
};

function when(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString();
}

export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setJobs(await api.listJobs());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Refresh while something is in flight so the list reflects a finished run
  // without the user reloading. The open job has its own live socket.
  useEffect(() => {
    if (!jobs.some((j) => j.status === "running" || j.status === "pending")) return;
    const t = setInterval(() => void reload(), 5000);
    return () => clearInterval(t);
  }, [jobs, reload]);

  const remove = async (job: Job) => {
    const withOutput = confirm(
      "Also delete the generated audio on the pod?\n\nOK = delete job and its files.\nCancel = delete the job row only, keep the files.",
    );
    try {
      await api.deleteJob(job.id, withOutput);
      if (open === job.id) setOpen(null);
      void reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">Jobs</h1>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={reload} disabled={loading}>
          <RefreshCcw className={cn("size-4", loading && "animate-spin")} />
        </Button>
      </div>

      {jobs.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Nothing has been generated yet.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {jobs.map((job) => {
            const items = (job.params.items as unknown[] | undefined)?.length ?? 0;
            const isOpen = open === job.id;
            return (
              <Card key={job.id}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                      onClick={() => setOpen(isOpen ? null : job.id)}
                    >
                      <Badge variant="outline" className={cn("font-normal", TONE[job.status])}>
                        {job.status}
                      </Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {job.id.slice(0, 8)}
                      </span>
                      <span className="text-sm">
                        {items} script{items === 1 ? "" : "s"}
                        {job.result?.failed ? ` · ${job.result.failed} failed` : ""}
                      </span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        {when(job.created_at)}
                      </span>
                    </button>
                    <Button variant="ghost" size="icon" onClick={() => remove(job)}>
                      <Trash2 className="size-4" />
                    </Button>
                  </div>

                  {job.error && !isOpen && (
                    <p className="mt-2 truncate text-xs text-red-600 dark:text-red-400">
                      {job.error}
                    </p>
                  )}

                  {isOpen && (
                    <div className="mt-4 space-y-4 border-t pt-4">
                      <JobStream jobId={job.id} onFinished={() => void reload()} />
                      {job.status !== "failed" && <OutputPanel jobId={job.id} />}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
