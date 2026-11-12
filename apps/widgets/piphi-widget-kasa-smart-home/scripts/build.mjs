import { build } from "esbuild";

await build({
  entryPoints: {
    "kasa-widget": "src/widget.ts",
    "kasa-metrics-widget": "src/metrics-widget.ts",
  },
  outdir: "assets",
  outExtension: { ".js": ".mjs" },
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  sourcemap: false,
  legalComments: "none",
});
