// The desktop host's one way to ask its own app server for JSON. The app
// server is where the Gateway is reached from, so anything the host keeps on
// the Arco Server (the user's preferences, their ArcBot chats) goes through it.
const http = require("http");

// GET when `body` is null, POST otherwise. Never rejects: any failure, a
// non-200 answer included, resolves to `{ error }`.
function requestAppServerJson(baseUrl, route, body = null, timeoutMs = 15000) {
  const base = String(baseUrl || "").trim();
  if (!base) return Promise.resolve({ error: "The Arco app server is not available." });
  return new Promise((resolve) => {
    const payloadText = body == null ? "" : JSON.stringify(body);
    const req = http.request(`${base}${route}`, {
      method: body == null ? "GET" : "POST",
      headers: body == null ? {} : { "content-type": "application/json", "content-length": Buffer.byteLength(payloadText) },
    }, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        text += chunk;
      });
      res.on("end", () => {
        let parsed = null;
        try {
          parsed = JSON.parse(text || "{}");
        } catch {
          parsed = null;
        }
        if (res.statusCode === 200 && parsed && typeof parsed === "object") {
          resolve(parsed);
          return;
        }
        const detail = parsed?.detail ? String(parsed.detail) : `HTTP ${res.statusCode || "error"}`;
        resolve({ error: detail });
      });
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error("timed out")));
    req.on("error", (err) => resolve({ error: String(err?.message || err || "request failed") }));
    req.end(payloadText);
  });
}

module.exports = { requestAppServerJson };
