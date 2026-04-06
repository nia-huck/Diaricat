import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const __dirname = dirname(fileURLToPath(import.meta.url));
process.chdir(__dirname);

const port = parseInt(process.env.PORT || "8080", 10);
const server = await createServer({
  configFile: resolve(__dirname, "vite.config.ts"),
  root: __dirname,
  server: { port },
});
await server.listen();
server.printUrls();
