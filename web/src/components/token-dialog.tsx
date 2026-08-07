"use client";

import { useState } from "react";
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
import { api, getToken, setToken } from "@/lib/api";

/**
 * Where the API token is entered. It is kept in localStorage, so it survives a
 * reload but never leaves this browser — the pod does not hand it out, the
 * operator copies it from `OVS_AUTH_TOKEN`.
 */
export function TokenDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
}) {
  const [value, setValue] = useState(getToken());
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    const previous = getToken();
    setToken(value.trim());
    try {
      // Verify against a gated endpoint before declaring success — saving a
      // wrong token silently is how you end up debugging "everything 401s".
      await api.system();
      toast.success("Token accepted");
      onSaved?.();
      onOpenChange(false);
    } catch {
      setToken(previous);
      toast.error("That token was rejected — nothing was saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>API token</DialogTitle>
          <DialogDescription>
            This pod is reachable at a public URL, so the API requires a token.
            It is the value of <code>OVS_AUTH_TOKEN</code> on the pod.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="token">Token</Label>
          <Input
            id="token"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
            }}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy || !value.trim()}>
            {busy ? "Checking…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
