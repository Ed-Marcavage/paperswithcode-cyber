// Public-only screenshot networking. The proxy pins sockets to checked DNS
// results, so Chromium cannot re-resolve a checked name to a private address.
import { lookup } from "node:dns/promises";
import http from "node:http";
import { BlockList, connect, isIP } from "node:net";

const blocked = new BlockList();
for (const [network, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["192.168.0.0", 16], ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24],
  ["224.0.0.0", 4], ["240.0.0.0", 4],
]) blocked.addSubnet(network, prefix, "ipv4");
for (const [network, prefix] of [
  ["::", 96], ["64:ff9b::", 96], ["64:ff9b:1::", 48],
  ["100::", 64], ["2001::", 23], ["2001:db8::", 32], ["2002::", 16],
  ["3fff::", 20], ["fc00::", 7], ["fe80::", 10], ["fec0::", 10], ["ff00::", 8],
]) blocked.addSubnet(network, prefix, "ipv6");
const globalV6 = new BlockList();
globalV6.addSubnet("2000::", 3, "ipv6");

const mappedV6 = new BlockList();
mappedV6.addSubnet("::ffff:0:0", 96, "ipv6");

export function isPublicAddress(address) {
  const family = isIP(address);
  if (!family || address.includes("%")) return false;
  if (family === 6 && !globalV6.check(address, "ipv6") && !mappedV6.check(address, "ipv6")) return false;
  return !blocked.check(address, family === 6 ? "ipv6" : "ipv4");
}

export async function publicDestination(value, resolve = lookup) {
  let url;
  try { url = new URL(value); } catch { throw new Error("Invalid destination URL"); }
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password)
    throw new Error("Destination must be an HTTP(S) URL without credentials");
  const port = Number(url.port || (url.protocol === "https:" ? 443 : 80));
  if (![80, 443].includes(port)) throw new Error("Destination port must be 80 or 443");
  const host = url.hostname.replace(/^\[|\]$/g, "");
  let addresses;
  try {
    addresses = isIP(host) ? [{ address: host, family: isIP(host) }] : await resolve(host, { all: true, verbatim: true });
  } catch { throw new Error("Destination hostname could not be resolved"); }
  if (!addresses.length || addresses.some(({ address }) => !isPublicAddress(address)))
    throw new Error("Destination resolves to a non-public address");
  return { url, host, port, addresses };
}

export async function interceptPublicRequest(route, rejected) {
  try { await publicDestination(route.request().url()); }
  catch (error) {
    rejected(error.message);
    await route.abort("blockedbyclient");
    return;
  }
  await route.continue();
}

export async function publicProxy(rejected) {
  const sockets = new Set();
  const track = (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    socket.on("error", () => socket.destroy());
    socket.setTimeout(30000, () => socket.destroy());
    return socket;
  };
  const server = http.createServer(async (request, response) => {
    let destination;
    try { destination = await publicDestination(request.url); }
    catch (error) {
      rejected(error.message);
      response.writeHead(403).end("Destination rejected");
      return;
    }
    const { url, port, addresses } = destination;
    if (url.protocol !== "http:") { response.writeHead(400).end(); return; }
    // A literal IP bypasses further DNS. Host stays the requested public host.
    const headers = { ...request.headers, host: url.host };
    delete headers["proxy-authorization"];
    delete headers["proxy-connection"];
    const upstream = http.request({ hostname: addresses[0].address, port,
      path: url.pathname + url.search, method: request.method, agent: false,
      headers,
    }, (incoming) => {
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
    });
    upstream.on("socket", track);
    upstream.on("error", () => { if (!response.headersSent) response.writeHead(502); response.end(); });
    request.on("aborted", () => upstream.destroy());
    request.pipe(upstream);
  });
  server.on("connection", track);
  server.on("connect", async (request, client, head) => {
    let destination;
    try { destination = await publicDestination(`https://${request.url}`); }
    catch (error) {
      rejected(error.message);
      client.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
      return;
    }
    const upstream = track(connect({ host: destination.addresses[0].address, port: destination.port }));
    upstream.once("connect", () => {
      client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head.length) upstream.write(head);
      upstream.pipe(client);
      client.pipe(upstream);
    });
    upstream.on("error", () => client.destroy());
    client.on("close", () => upstream.destroy());
  });
  server.on("upgrade", (_request, socket) => socket.destroy());
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    server: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((resolve) => {
      for (const socket of sockets) socket.destroy();
      server.close(resolve);
    }),
  };
}
