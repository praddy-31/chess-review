// Builds the app on macOS, Windows or Linux: freezes the engine
// (tools/build_engine.py), then runs `tauri build`. On a Mac it then removes
// the DMG step's leftover and opens the DMG (skipped with NO_OPEN=1).
// Run by `npm run build` in tauri/.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const tauri = join(root, "tauri");
const win = process.platform === "win32";

function run(cmd, args, opts = {}) {
  console.log("+", cmd, args.join(" "));
  const r = spawnSync(cmd, args, { stdio: "inherit", shell: win, ...opts });
  return r.status === 0;
}

// any Python 3.10+ works: the script makes engine/.venv itself. Python is started without a
// shell: on Windows cmd.exe would read the "<" in the version check as a redirect (and split
// paths with spaces), so every Python looked missing.
const pythons = win ? [["py", ["-3"]], ["python", []]] : [["python3", []], ["python", []]];
const py = pythons.find(([c, a]) => spawnSync(c, [...a, "-c", "import sys; sys.exit(sys.version_info < (3, 10))"]).status === 0);
if (!py) { console.error("No Python 3.10+ found: install it from python.org (or your package manager)"); process.exit(1); }
if (!run(py[0], [...py[1], join(root, "tools", "build_engine.py")], { shell: false })) process.exit(1);

// CI=true: no Finder window dressing for the DMG, which needs a logged-in GUI
if (!run("npx", ["tauri", "build"], { cwd: tauri, env: { ...process.env, CI: "true" } })) process.exit(1);

if (process.platform === "darwin") {
  const bundle = join(tauri, "src-tauri", "target", "release", "bundle");
  const macos = join(bundle, "macos");
  if (existsSync(macos)) for (const f of readdirSync(macos)) if (/^rw\..*\.dmg$/.test(f)) rmSync(join(macos, f));
  const dmgs = existsSync(join(bundle, "dmg")) ? readdirSync(join(bundle, "dmg")).filter(f => f.endsWith(".dmg")) : [];
  if (dmgs.length && !process.env.NO_OPEN) spawnSync("open", [join(bundle, "dmg", dmgs[0])]);
}
console.log("built: tauri/src-tauri/target/release/bundle/");
