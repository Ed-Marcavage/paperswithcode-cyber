import { defineConfig, mergeConfig, type Plugin, type ProxyOptions } from "vite";
import upstream from "./vite.config";

// On the same URL, browsers get setup instructions and MCP clients get Streamable HTTP.
const mcp: ProxyOptions = {
  target: "http://mcp:7860",
  bypass(req) {
    const path = req.url?.split("?")[0];
    if ((path === "/mcp" || path === "/mcp/") && req.method === "GET"
        && !req.headers.accept?.includes("text/event-stream")) return "/index.html";
  },
  rewrite: path => path.replace(/^\/mcp\/health(?=[?]|$)/, "/health")
    .replace(/^\/mcp\/schema(?=[?]|$)/, "/docs").replace(/^\/mcp\/(?=[?]|$)/, "/mcp"),
};
const readOnly: Plugin = {
  name: "catalog-read-only",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      // Vite's "/api" proxy matches the raw URL prefix, including "/api%2F…".
      if (!req.url?.startsWith("/api") || ["GET", "HEAD", "OPTIONS"].includes(req.method || "")) return next();
      res.writeHead(405, { Allow: "GET, HEAD, OPTIONS" });
      res.end("This catalog is read-only.");
    });
  },
};
export default defineConfig(async env => {
  const base = typeof upstream === "function" ? await upstream(env) : await upstream;
  return mergeConfig(base, {
    plugins: [readOnly],
    server: {
      host: "0.0.0.0", port: 8085, strictPort: true,
      proxy: {
        "/api": { target: "http://backend:8000", changeOrigin: true },
        "/health": { target: "http://backend:8000", changeOrigin: true },
        "/mcp": mcp,
        "/.well-known/mcp": { target: "http://mcp:7860" },
      },
    },
  });
});
