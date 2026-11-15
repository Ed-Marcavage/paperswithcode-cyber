import assert from "node:assert/strict";
import test from "node:test";
import http from "node:http";
import { isPublicAddress, publicDestination, interceptPublicRequest, publicProxy } from "./public_network.mjs";

for (const address of ["0.0.0.0", "127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.255",
  "192.168.0.1", "169.254.169.254", "100.64.0.1", "224.0.0.1", "255.255.255.255",
  "::", "::1", "fc00::1", "fd12::1", "fe80::1", "fe80::1%en0", "fec0::1", "ff02::1",
  "::ffff:127.0.0.1", "::ffff:10.1.2.3", "::ffff:169.254.1.1", "2002:7f00:1::", "64:ff9b::7f00:1",
  "2001:db8::1", "not-an-address"]) {
  test(`reject ${address}`, () => assert.equal(isPublicAddress(address), false));
}
for (const address of ["8.8.8.8", "1.1.1.1", "172.15.255.255", "172.32.0.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
  test(`allow ${address}`, () => assert.equal(isPublicAddress(address), true));

for (const url of ["file:///etc/passwd", "data:text/html,hi", "ftp://example.com", "javascript:alert(1)",
  "http://127.1", "http://2130706433", "http://0x7f000001", "http://0177.0.0.1", "http://[::ffff:7f00:1]",
  "http://user:pass@example.com", "https://example.com:8000"]) {
  test(`reject URL ${url}`, async () => assert.rejects(publicDestination(url)));
}
test("all DNS addresses must be public, including IPv6", async () => {
  const mixed = async () => [{ address: "8.8.8.8", family: 4 }, { address: "fd00::1", family: 6 }];
  await assert.rejects(publicDestination("https://example.com", mixed), /non-public/);
  await assert.rejects(publicDestination("https://example.com", async () => []), /non-public/);
  await assert.rejects(publicDestination("https://example.com", async () => { throw new Error(); }), /resolved/);
});
test("approved DNS answers are returned for socket pinning", async () => {
  const addresses = [{ address: "8.8.8.8", family: 4 }, { address: "2606:4700::1111", family: 6 }];
  const destination = await publicDestination("https://example.com/post", async () => addresses);
  assert.equal(destination.host, "example.com");
  assert.deepEqual(destination.addresses, addresses);
});
test("interception blocks page, redirect and subresource requests before continuation", async () => {
  for (const url of ["http://10.1.2.3/", "http://[::1]/redirect", "file:///etc/passwd", "http://169.254.169.254/image"]) {
    let aborted = false, reason;
    await interceptPublicRequest({ request: () => ({ url: () => url }),
      abort: async () => { aborted = true; }, continue: async () => assert.fail("Unsafe request continued"),
    }, (value) => { reason = value; });
    assert.ok(aborted && reason);
  }
});
test("proxy rejects private HTTP and CONNECT destinations without a browser", async () => {
  const rejected = [];
  const proxy = await publicProxy((reason) => rejected.push(reason));
  const endpoint = new URL(proxy.server);
  try {
    for (const method of ["GET", "CONNECT"]) {
      await new Promise((resolve, reject) => {
        const request = http.request({ hostname: endpoint.hostname, port: endpoint.port, method,
          path: method === "CONNECT" ? "[::1]:443" : "http://127.0.0.1/private" });
        request.on(method === "CONNECT" ? "connect" : "response", (response, socket) => {
          assert.equal(response.statusCode, 403);
          if (socket) socket.destroy(); else response.resume();
          resolve();
        });
        request.on("error", reject);
        request.end();
      });
    }
    assert.equal(rejected.length, 2);
  } finally { await proxy.close(); }
});
