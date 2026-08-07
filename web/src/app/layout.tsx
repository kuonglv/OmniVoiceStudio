import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

import { SiteHeader } from "@/components/site-header";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "OmniVoice Studio",
  description: "Reference-voice library and script-to-speech on a GPU box",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // No next/font here on purpose: `next build` runs inside the Docker image,
    // where fetching Google Fonts would make the build depend on the network.
    <html lang="en" suppressHydrationWarning className="h-full antialiased">
      <body className="min-h-full">
        {/* Set the theme class before hydration so the page never flashes light
            then dark. beforeInteractive injects into the initial HTML. */}
        <Script
          id="theme-fouc"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var s=localStorage.getItem('theme')||'system';var t=s==='system'?(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):s;var r=document.documentElement;r.classList.remove('light','dark');r.classList.add(t);r.style.colorScheme=t;}catch(e){}})();`,
          }}
        />
        <ThemeProvider>
          <div className="flex min-h-screen flex-col">
            <SiteHeader />
            <main className="mx-auto w-full max-w-6xl flex-1 p-6">{children}</main>
          </div>
          <Toaster richColors />
        </ThemeProvider>
      </body>
    </html>
  );
}
