// npm 12 blocks dependency install scripts by default and a package cannot
// approve itself, so this hook is only a fast path on older npm. The extension
// provisions the bridge on first use either way.
//
// A source checkout has no dist/ until `npm run build:plugins`, so a missing
// script is not an error: it must never fail `npm install` in the repository.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("./dist/bootstrap.js", import.meta.url));
if (existsSync(script)) execFileSync(process.execPath, [script], { stdio: "inherit" });
