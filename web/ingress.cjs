// Capture the actual socket peer before Next converts IncomingMessage to Request.
// Next preserves caller-supplied XFF, so that header alone is not a trust boundary.
// CommonJS is required by Node's --require startup hook.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const http = require("node:http");
const originalEmit = http.Server.prototype.emit;
http.Server.prototype.emit = function (event, ...args) {
  if (event === "request") {
    const request = args[0];
    const forwarded = String(request.headers["x-forwarded-for"] || "");
    request.headers["x-talentflow-ip-chain"] =
      `${forwarded ? `${forwarded},` : ""}${request.socket.remoteAddress || ""}`;
  }
  return originalEmit.call(this, event, ...args);
};
