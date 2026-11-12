import { build } from "esbuild";

await build({
  entryPoints: ["src/widget.ts"],
  outfile: "assets/awair-widget.mjs",
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  sourcemap: false,
  legalComments: "none",
});
