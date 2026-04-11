import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { parse } from "node:url";

import next from "next";

const dev = false;
const hostname = process.env.HOSTNAME || "0.0.0.0";
const port = Number(process.env.PORT || 3000);
const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();
const staticRoot = resolve(process.cwd(), ".next", "static");

const MIME_TYPES = {
  ".css": "text/css; charset=UTF-8",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".js": "application/javascript; charset=UTF-8",
  ".json": "application/json; charset=UTF-8",
  ".map": "application/json; charset=UTF-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=UTF-8",
  ".webp": "image/webp",
};

function contentTypeFor(pathname) {
  return MIME_TYPES[extname(pathname).toLowerCase()] || "application/octet-stream";
}

function resolveStaticPath(pathname) {
  const encodedRelative = pathname.replace(/^\/_next\/static\//, "");
  let relative;
  try {
    relative = decodeURIComponent(encodedRelative);
  } catch {
    return null;
  }
  const normalized = normalize(relative).replace(/^(\.\.(\/|\\|$))+/, "");
  const absolute = resolve(join(staticRoot, normalized));
  if (!absolute.startsWith(staticRoot)) {
    return null;
  }
  return absolute;
}

async function serveStaticAsset(req, res, pathname) {
  const filePath = resolveStaticPath(pathname);
  if (!filePath) {
    res.statusCode = 400;
    res.end("Bad Request");
    return true;
  }

  try {
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) {
      console.error("[custom-next-server] static miss: not a file", { pathname, filePath });
      return false;
    }

    res.statusCode = 200;
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    res.setHeader("Content-Type", contentTypeFor(filePath));
    res.setHeader("Content-Length", fileStat.size);

    if (req.method === "HEAD") {
      res.end();
      return true;
    }

    createReadStream(filePath).pipe(res);
    return true;
  } catch (error) {
    console.error("[custom-next-server] static miss", { pathname, filePath, error });
    return false;
  }
}

app.prepare().then(() => {
  createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url || "/", true);
      const pathname = parsedUrl.pathname || "/";
      res.setHeader("X-Codex-Path", pathname);
      console.error("[custom-next-server] req", pathname);
      if (pathname.startsWith("/_next/static/")) {
        const served = await serveStaticAsset(req, res, pathname);
        if (served) {
          return;
        }
      }

      await handle(req, res, parsedUrl);
    } catch (error) {
      console.error("[custom-next-server] request failed", error);
      res.statusCode = 500;
      res.end("Internal Server Error");
    }
  }).listen(port, hostname, () => {
    console.log(`[custom-next-server] ready on http://${hostname}:${port}`);
  });
});
