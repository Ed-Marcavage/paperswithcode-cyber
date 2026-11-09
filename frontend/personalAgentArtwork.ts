import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const artwork = [
  {
    file: "dots.svg",
    url: "https://images.ctfassets.net/8su2tbn87fck/PulStHeDuz5begF06sEwk/c2080ae53243122046ba61074a5f0bd2/dots-o-updated.svg",
    sha256: "1e351734a2db757f16f367140714cab4c999c5382ef428f914127efe65841ffc",
  },
  {
    file: "grok-bot.jpg",
    url: "https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/19/b5/df/19b5df74-baf6-120d-40cf-7deb33202e21/app-0-0-1x_U007epad-0-0-0-1-0-0-0-85-220.png/100x100bb.jpg",
    sha256: "54073ff49ec0381f74838d4f2ff9a1364076ad0aa1e135ec7a90334ebec37ddf",
  },
  {
    file: "muse.svg",
    url: "https://muse.ai/images/favicon/app-squiggle.svg",
    sha256: "6373d89d274258a38432f3c3729cd716498b8ded849b174a7998683dcf4aaba5",
  },
];

export async function loadPersonalAgentArtwork(cache: string): Promise<Record<string, string>> {
  await mkdir(cache, { recursive: true });
  const icons: Record<string, string> = {};
  for (const { file, url, sha256 } of artwork) {
    const destination = path.join(cache, file);
    let bytes: Buffer;
    let fetched = false;
    try {
      bytes = await readFile(destination);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      const response = await fetch(url, { signal: AbortSignal.timeout(20_000) });
      if (!response.ok) throw new Error(`Could not fetch ${file} (HTTP ${response.status}). Seed ${destination} to build offline.`);
      bytes = Buffer.from(await response.arrayBuffer());
      fetched = true;
    }
    if (createHash("sha256").update(bytes).digest("hex") !== sha256) {
      throw new Error(`Unexpected SHA-256 for ${file}. Seed ${destination} with the pinned artwork (${sha256}).`);
    }
    if (fetched) {
      const temporary = `${destination}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, bytes);
        await rename(temporary, destination);
      } finally {
        await rm(temporary, { force: true });
      }
    }
    const mime = file.endsWith(".svg") ? "image/svg+xml" : "image/jpeg";
    icons[file] = `data:${mime};base64,${bytes.toString("base64")}`;
  }
  return icons;
}
