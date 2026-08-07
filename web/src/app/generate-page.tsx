"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, FileText, Loader2, Upload, Wand2 } from "lucide-react";
import { toast } from "sonner";

import { JobStream } from "@/components/job-stream";
import { OutputPanel } from "@/components/output-panel";
import { VOICE_CUSTOM, VOICE_NONE, VoiceSelect } from "@/components/voice-select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  type AsrParams,
  type JobStatus,
  type ReferenceVoice,
  type SynthesisParams,
  type SystemInfo,
} from "@/lib/api";

const DEFAULT_SYNTHESIS: SynthesisParams = {
  voice: VOICE_NONE,
  ref_audio: "",
  ref_text: "",
  language: "en",
  speed: 1.0,
  num_step: 32,
  guidance_scale: 2.0,
  audio_chunk_duration: 15.0,
  audio_chunk_threshold: 30.0,
  max_chars_per_chunk: 300,
  model_id: null,
  device: null,
};

const DEFAULT_ASR: AsrParams = {
  model: null,
  output_format: "srt",
  max_line_count: 1,
  max_line_width: 35,
  language: null,
  initial_prompt: null,
  word_timestamps: true,
};

export function GeneratePage() {
  const [voices, setVoices] = useState<ReferenceVoice[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [syn, setSyn] = useState<SynthesisParams>(DEFAULT_SYNTHESIS);
  const [asr, setAsr] = useState<AsrParams>(DEFAULT_ASR);
  const [makeSrt, setMakeSrt] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const [mode, setMode] = useState<"paste" | "upload">("paste");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobDone, setJobDone] = useState<JobStatus | null>(null);

  useEffect(() => {
    api.listVoices().then(setVoices).catch(() => setVoices([]));
    api.system().then(setSystem).catch(() => setSystem(null));
  }, []);

  const set = <K extends keyof SynthesisParams>(key: K, value: SynthesisParams[K]) =>
    setSyn((prev) => ({ ...prev, [key]: value }));

  const charCount = text.trim().length;
  // OmniVoice runs roughly real-time-ish on a modern GPU; at ~15 chars/second
  // of speech this is close enough to warn before someone queues an hour.
  const estMinutes = charCount / 15 / 60;

  const submit = useCallback(async () => {
    setSubmitting(true);
    setJobDone(null);
    try {
      const payload = { ...syn, ref_audio: syn.ref_audio || null, ref_text: syn.ref_text || null };
      const accepted =
        mode === "upload"
          ? await (() => {
              const form = new FormData();
              files.forEach((f) => form.append("files", f));
              form.append("make_srt", String(makeSrt));
              form.append("synthesis", JSON.stringify(payload));
              form.append("asr", JSON.stringify(asr));
              return api.generateUpload(form);
            })()
          : await api.generate({
              items: [{ name: title.trim() || "script", text }],
              make_srt: makeSrt,
              synthesis: payload,
              asr,
            });
      setJobId(accepted.job_id);
      toast.success(`Queued ${accepted.items} script(s)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [syn, asr, makeSrt, mode, files, title, text]);

  const canSubmit =
    !submitting && (mode === "paste" ? charCount > 0 : files.length > 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        {/* ---- the script ------------------------------------------------ */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>Script</CardTitle>
            <div className="flex gap-1">
              <Button
                variant={mode === "paste" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setMode("paste")}
              >
                <FileText className="size-4" />
                Paste
              </Button>
              <Button
                variant={mode === "upload" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setMode("upload")}
              >
                <Upload className="size-4" />
                Upload
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {mode === "paste" ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="title">Name</Label>
                  <Input
                    id="title"
                    placeholder="chapter-01"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Becomes the output filename.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="text">Text</Label>
                  <Textarea
                    id="text"
                    rows={18}
                    className="font-mono text-sm"
                    placeholder="Paste the script here. Keep sentence punctuation — OmniVoice splits long text on '.', '!' and '?', and refuses text it cannot split."
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {charCount.toLocaleString()} characters
                    {charCount > 0 && ` · roughly ${estMinutes.toFixed(1)} min of speech`}
                  </p>
                </div>
              </>
            ) : (
              <div className="space-y-3">
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  accept=".txt,.md,.zip"
                  className="hidden"
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                />
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="flex w-full flex-col items-center gap-2 rounded-md border border-dashed p-10 text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                >
                  <Upload className="size-6" />
                  Choose .txt / .md files, or one .zip of them
                </button>
                {files.length > 0 && (
                  <ul className="space-y-1 text-sm">
                    {files.map((f) => (
                      <li key={f.name} className="flex justify-between gap-4">
                        <span className="truncate font-mono text-xs">{f.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {(f.size / 1024).toFixed(1)} KB
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-xs text-muted-foreground">
                  Each file becomes one WAV, named after it. Files must be UTF-8.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ---- settings --------------------------------------------------- */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Voice</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <VoiceSelect
                value={syn.voice}
                onChange={(v) => set("voice", v)}
                voices={voices}
              />
              {(syn.voice === VOICE_NONE || syn.voice === VOICE_CUSTOM) && (
                <>
                  {syn.voice === VOICE_CUSTOM && (
                    <div className="space-y-1.5">
                      <Label htmlFor="refaudio">Reference clip path</Label>
                      <Input
                        id="refaudio"
                        placeholder="/workspace/my-clip.wav"
                        value={syn.ref_audio ?? ""}
                        onChange={(e) => set("ref_audio", e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        A path on the pod, not on your laptop. Prefer adding it to
                        the library instead — that survives a pod restart.
                      </p>
                    </div>
                  )}
                  {syn.voice === VOICE_CUSTOM && (
                    <div className="space-y-1.5">
                      <Label htmlFor="reftext">Reference transcript</Label>
                      <Textarea
                        id="reftext"
                        rows={2}
                        value={syn.ref_text ?? ""}
                        onChange={(e) => set("ref_text", e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Exactly what the clip says. Blank = transcribed on load.
                      </p>
                    </div>
                  )}
                  {syn.voice === VOICE_NONE && (
                    <p className="text-xs text-muted-foreground">
                      Without a reference the model picks its own voice and can
                      drift in timbre and loudness over a long script.
                    </p>
                  )}
                </>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="lang">Language</Label>
                  <Input
                    id="lang"
                    placeholder="en"
                    value={syn.language ?? ""}
                    onChange={(e) => set("language", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="speed">Speed</Label>
                  <Input
                    id="speed"
                    type="number"
                    step="0.05"
                    min="0.5"
                    max="1.5"
                    value={syn.speed}
                    onChange={(e) => set("speed", parseFloat(e.target.value) || 1)}
                  />
                </div>
              </div>
              {(syn.speed < 0.9 || syn.speed > 1.1) && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  Speed stretches the duration the model has to fill. Outside
                  0.9–1.1 the speech drawls and picks up artifacts.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Subtitles</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-3">
                <Switch id="srt" checked={makeSrt} onCheckedChange={setMakeSrt} />
                <Label htmlFor="srt">Generate .srt with Whisper</Label>
              </div>
              {makeSrt && system && !system.whisper_available && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  The `whisper` binary is not on this box — the audio will still
                  be generated, but the subtitle step will be skipped.
                </p>
              )}
              {makeSrt && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="wmodel">Whisper model</Label>
                    <Input
                      id="wmodel"
                      placeholder={system?.defaults.whisper_model ?? "small"}
                      value={asr.model ?? ""}
                      onChange={(e) => setAsr({ ...asr, model: e.target.value || null })}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="wwidth">Max line width</Label>
                    <Input
                      id="wwidth"
                      type="number"
                      value={asr.max_line_width}
                      onChange={(e) =>
                        setAsr({ ...asr, max_line_width: parseInt(e.target.value) || 35 })
                      }
                    />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-0">
              <button
                type="button"
                className="flex w-full items-center justify-between text-sm font-medium"
                onClick={() => setAdvanced((v) => !v)}
              >
                Model settings
                <ChevronDown
                  className={`size-4 transition-transform ${advanced ? "rotate-180" : ""}`}
                />
              </button>
            </CardHeader>
            {advanced && (
              <CardContent className="space-y-3 pt-4">
                <div className="grid grid-cols-2 gap-3">
                  <NumField
                    label="Diffusion steps"
                    value={syn.num_step}
                    onChange={(v) => set("num_step", v)}
                    hint="32 = default, 16 ≈ twice as fast and rougher"
                  />
                  <NumField
                    label="Guidance scale"
                    step="0.1"
                    value={syn.guidance_scale}
                    onChange={(v) => set("guidance_scale", v)}
                    hint="2.0 is tuned; higher over-articulates"
                  />
                  <NumField
                    label="Chunk duration (s)"
                    step="0.5"
                    value={syn.audio_chunk_duration}
                    onChange={(v) => set("audio_chunk_duration", v)}
                  />
                  <NumField
                    label="Chunk threshold (s)"
                    step="0.5"
                    value={syn.audio_chunk_threshold}
                    onChange={(v) => set("audio_chunk_threshold", v)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="device">Device</Label>
                  <Input
                    id="device"
                    placeholder={system?.defaults.device ?? "cuda:0"}
                    value={syn.device ?? ""}
                    onChange={(e) => set("device", e.target.value || null)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="model">Model id</Label>
                  <Input
                    id="model"
                    placeholder={system?.defaults.model_id ?? "k2-fsa/OmniVoice"}
                    value={syn.model_id ?? ""}
                    onChange={(e) => set("model_id", e.target.value || null)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Changing this loads a second model into VRAM alongside the
                    first.
                  </p>
                </div>
              </CardContent>
            )}
          </Card>

          <Button className="w-full" size="lg" disabled={!canSubmit} onClick={submit}>
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Wand2 className="size-4" />
            )}
            Generate
          </Button>
        </div>
      </div>

      {/* ---- the run ------------------------------------------------------ */}
      {jobId && (
        <Card>
          <CardHeader>
            <CardTitle>Run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <JobStream jobId={jobId} onFinished={setJobDone} />
            {jobDone && jobDone !== "failed" && <OutputPanel jobId={jobId} />}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  step = "1",
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: string;
  hint?: string;
}) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
      />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
