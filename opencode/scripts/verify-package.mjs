import { execFileSync } from "node:child_process";

const output = execFileSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
  cwd: new URL("..", import.meta.url),
  encoding: "utf8",
});
const result = JSON.parse(output)[0];
const names = new Set(result.files.map(({ path }) => path));

for (const required of ["dist/plugin.js", "skills/luminary-memory/SKILL.md", "README.md"]) {
  if (!names.has(required)) {
    throw new Error(`npm pack is missing ${required}`);
  }
}

console.log("npm pack contents: PASS");
