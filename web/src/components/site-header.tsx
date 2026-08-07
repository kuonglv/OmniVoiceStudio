"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AudioLines, KeyRound, Mic, Radio } from "lucide-react";

import { ThemeToggle } from "@/components/theme-toggle";
import { TokenDialog } from "@/components/token-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, getToken, type Health } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Generate", icon: AudioLines },
  { href: "/voices/", label: "Voices", icon: Mic },
  { href: "/jobs/", label: "Jobs", icon: Radio },
];

/**
 * Nav plus a live view of what the box can actually do.
 *
 * The GPU badge is the first thing to check when audio "doesn't work": a pod
 * booted on a CPU-only machine, or without the `omnivoice` package, looks
 * identical in the UI until you read it.
 */
export function SiteHeader() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(Boolean(getToken()));
    api
      .health()
      .then((h) => {
        setHealth(h);
        // Prompt for the token straight away rather than after the first 401.
        if (h.auth_required && !getToken()) setTokenOpen(true);
      })
      .catch(() => setHealth(null));
  }, []);

  const gpu = health
    ? health.cuda_available
      ? { text: health.gpu_name ?? "GPU", tone: "ok" as const }
      : { text: "No GPU", tone: "warn" as const }
    : { text: "…", tone: "muted" as const };

  return (
    <header className="border-b">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-1 px-6 py-3">
        <span className="mr-4 font-semibold tracking-tight">OmniVoice Studio</span>
        <nav className="flex items-center gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Button
                key={href}
                render={<Link href={href} />}
                variant={active ? "secondary" : "ghost"}
                size="sm"
              >
                <Icon className="size-4" />
                {label}
              </Button>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <Badge
            variant="outline"
            className={cn(
              "font-normal",
              gpu.tone === "warn" && "border-amber-500/50 text-amber-600 dark:text-amber-400",
            )}
            title={
              health
                ? `torch ${health.torch ?? "not installed"} · omnivoice ${
                    health.omnivoice_installed ? "installed" : "missing"
                  } · model ${health.model_loaded ? "loaded" : "not loaded"}`
                : "backend unreachable"
            }
          >
            {gpu.text}
          </Badge>
          {health?.auth_required && (
            <Button
              variant={hasToken ? "ghost" : "destructive"}
              size="sm"
              onClick={() => setTokenOpen(true)}
            >
              <KeyRound className="size-4" />
              {hasToken ? "Token" : "Set token"}
            </Button>
          )}
          <ThemeToggle />
        </div>
      </div>

      <TokenDialog
        open={tokenOpen}
        onOpenChange={setTokenOpen}
        onSaved={() => setHasToken(Boolean(getToken()))}
      />
    </header>
  );
}
