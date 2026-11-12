import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { createHash } from "node:crypto";

const sdk = fileURLToPath(import.meta.resolve("piphi-network-widget-sdk"));
const root = new URL("../", import.meta.url);
const integration = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));
const overviewTranslations = {
  en: {
    "plex.title.servers": "Plex servers",
    "plex.activity.label": "Plex server activity",
    "plex.metric.servers": "Servers",
    "plex.metric.streams": "Streams",
    "plex.metric.transcodes": "Transcodes",
    "plex.status.updating": "Updating Plex…",
    "plex.status.stale": "Plex data may be out of date",
    "plex.status.offline": "Plex is offline",
    "plex.status.error": "Plex readings are unavailable",
    "plex.status.waiting": "Waiting for Plex",
    "common.retry": "Retry",
  },
  ar: {
    "plex.title.servers": "خوادم Plex",
    "plex.activity.label": "نشاط خادم Plex",
    "plex.metric.servers": "الخوادم",
    "plex.metric.streams": "عمليات البث",
    "plex.metric.transcodes": "التحويلات",
    "plex.status.updating": "جارٍ تحديث Plex…",
    "plex.status.stale": "قد تكون بيانات Plex قديمة",
    "plex.status.offline": "Plex غير متصل",
    "plex.status.error": "قراءات Plex غير متاحة",
    "plex.status.waiting": "في انتظار Plex",
    "common.retry": "إعادة المحاولة",
  },
};
const mediaTranslations = {
  en: {
    "plex.title.recently_added": "Recently Added",
    "plex.title.continue_watching": "Continue Watching",
    "plex.title.library": "Plex Search / Library",
    "plex.title.default": "Plex",
    "plex.action.refresh": "Refresh Plex",
    "plex.status.loading": "Loading Plex…",
    "plex.status.reconnecting": "Reconnecting to Plex…",
    "plex.status.live": "Live · updated %TIME%",
    "plex.status.stale_results": "Connection lost · showing previous results",
    "plex.status.denied": "Plex access needs permission",
    "plex.status.offline_retry": "Plex is offline · retrying",
    "plex.status.unavailable_retry": "Plex is unavailable · retrying",
    "plex.media.label": "Plex media",
    "plex.media.empty": "No matching media on this server.",
    "plex.media.untitled": "Untitled",
    "plex.media.fallback": "Media",
    "plex.media.watched": "%TITLE%: %PERCENT%% watched",
    "plex.media.kind.movie": "Movie",
    "plex.media.kind.episode": "Episode",
    "plex.media.kind.music": "Music",
  },
  ar: {
    "plex.title.recently_added": "المضاف حديثًا",
    "plex.title.continue_watching": "متابعة المشاهدة",
    "plex.title.library": "بحث ومكتبة Plex",
    "plex.title.default": "Plex",
    "plex.action.refresh": "تحديث Plex",
    "plex.status.loading": "جارٍ تحميل Plex…",
    "plex.status.reconnecting": "جارٍ إعادة الاتصال بـ Plex…",
    "plex.status.live": "مباشر · تم التحديث %TIME%",
    "plex.status.stale_results": "انقطع الاتصال · يتم عرض النتائج السابقة",
    "plex.status.denied": "يحتاج Plex إلى إذن للوصول",
    "plex.status.offline_retry": "Plex غير متصل · جارٍ إعادة المحاولة",
    "plex.status.unavailable_retry": "Plex غير متاح · جارٍ إعادة المحاولة",
    "plex.media.label": "وسائط Plex",
    "plex.media.empty": "لا توجد وسائط مطابقة على هذا الخادم.",
    "plex.media.untitled": "بلا عنوان",
    "plex.media.fallback": "وسائط",
    "plex.media.watched": "تمت مشاهدة %PERCENT%% من %TITLE%",
    "plex.media.kind.movie": "فيلم",
    "plex.media.kind.episode": "حلقة",
    "plex.media.kind.music": "موسيقى",
  },
};
const overviewDirectory = new URL("widgets/plex-server-overview/", root);
const overviewEntry = new URL("widgets/plex-server-overview/src/widget.js", root);
const overviewTemp = new URL("experiences/plex-media/assets/server-overview.build.js", root);
await build({ entryPoints: [fileURLToPath(overviewEntry)], outfile: fileURLToPath(overviewTemp), bundle: true,
  format: "esm", target: "es2022", alias: { "piphi-network-widget-sdk": sdk }, minify: false,
});
const overviewBytes = await readFile(overviewTemp);
await writeFile(new URL("experiences/plex-media/assets/server-overview.js", root), overviewBytes);
await writeFile(new URL("dist/widget.js", overviewDirectory), overviewBytes);
await rm(overviewTemp);
const overviewManifestPath = new URL("widget.manifest.json", overviewDirectory);
const overviewManifest = JSON.parse(await readFile(overviewManifestPath, "utf8"));
overviewManifest.version = "0.1.10";
overviewManifest.sdk_compatibility = { minimum: "0.6.0" };
overviewManifest.interaction_targets = [
  { id: "server-card", label: "Plex server overview", kind: "card", allowed_actions: ["more-info", "popout", "refresh"], default_action: "more-info" },
  { id: "connected", label: "Plex connection", kind: "binding", binding_slot_id: "connected", allowed_actions: ["more-info", "popout"], default_action: "more-info" },
  { id: "active-sessions", label: "Active Plex sessions", kind: "binding", binding_slot_id: "active-sessions", allowed_actions: ["more-info", "history", "popout"], default_action: "more-info" },
];
overviewManifest.layout = { min_height: 96, default_height: 112, max_height: 140 };
overviewManifest.integrity = `sha384-${createHash("sha384").update(overviewBytes).digest("base64")}`;
await writeFile(overviewManifestPath, JSON.stringify(overviewManifest, null, 2) + "\n");
const registeredOverview = {
  ...overviewManifest,
  translations: overviewTranslations,
  entry: "/widgets/plex-server-overview/dist/widget.js",
  runtime: "prebuilt_bundle",
  previews: {
    light: "/widgets/plex-server-overview/preview-light.svg",
    dark: "/widgets/plex-server-overview/preview-dark.svg",
  },
  host_bridge: { protocol: "piphi.widget.host", version: "1", events: ["ready", "resize"] },
};
integration.ui.widget_packages = integration.ui.widget_packages.filter((pkg) => pkg.id !== overviewManifest.id);
integration.ui.widget_packages.unshift(registeredOverview);
const packages = [
  ["recently-added", "Recently Added"],
  ["continue-watching", "Continue Watching"],
  ["library-search", "Plex Search / Library"],
];
const interactionTargets = {
  "recently-added": { id: "recently-added-card", label: "Recently added Plex media" },
  "continue-watching": { id: "continue-watching-card", label: "Continue watching Plex media" },
  "library-search": { id: "library-search-card", label: "Plex library results" },
};
for (const [slug, name] of packages) {
  const directory = new URL(`widgets/${slug}/`, root);
  await mkdir(new URL("dist/", directory), { recursive: true });
  const outfile = new URL("dist/widget.js", directory);
  await build({ entryPoints: [fileURLToPath(new URL("widgets/live-media/entry.js", root))],
    outfile: fileURLToPath(outfile), bundle: true, format: "esm", target: "es2022",
    alias: { "piphi-network-widget-sdk": sdk }, minify: false,
  });
  const bytes = await readFile(outfile);
  const manifest = {
    id: `io.piphi.plex.${slug}`, name, version: "0.1.6", entry: "./dist/widget.js",
    integrity: `sha384-${createHash("sha384").update(bytes).digest("base64")}`,
    binding_modes: ["read"], value_kinds: ["json"], capability_requirements: [],
    sdk_compatibility: { minimum: "0.6.0" }, settings_schema_version: "1",
    interaction_targets: [{ ...interactionTargets[slug], kind: "card", allowed_actions: ["more-info", "popout", "refresh"], default_action: "more-info" }],
    conformance: { accessibility: "wcag2.2-aa", keyboard: true, themes: ["light", "dark"], directions: ["ltr", "rtl"],
      states: ["loading", "live", "stale", "offline", "reconnecting", "denied", "error"] },
    previews: { light: "./preview-light.svg", dark: "./preview-dark.svg" },
    settings: [
      { id: "title", type: "text", label: "Title", default: name },
      { id: "limit", type: "number", label: "Items (1–24)", default: 8 },
      { id: "refresh-seconds", type: "number", label: "Refresh seconds (15–300)", default: 60 },
      { id: "show-summary", type: "boolean", label: "Show one-line summaries", default: false },
      ...(slug === "library-search" ? [
        { id: "query", type: "text", label: "Search query (all server libraries)", default: "" },
        { id: "collection-id", type: "text", label: "Library ID (used when query is empty)", default: "" },
      ] : []),
    ],
    layout: { min_height: 112, default_height: 112, max_height: 220 },
    security: { permissions: ["host.queryMedia"], sandbox: ["allow-scripts"], csp: { connect_src: [] } },
  };
  await writeFile(new URL("widget.manifest.json", directory), JSON.stringify(manifest, null, 2) + "\n");
  for (const theme of ["light", "dark"]) {
    await writeFile(new URL(`preview-${theme}.svg`, directory), `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="220" viewBox="0 0 400 220"><rect width="400" height="220" rx="16" fill="${theme === "dark" ? "#172033" : "#ffffff"}"/><g font-family="sans-serif" fill="${theme === "dark" ? "#f1f5f9" : "#0f172a"}"><text x="24" y="36" font-size="18">${name}</text><text x="24" y="58" font-size="12">Plex server</text>${[0, 1].map((i) => `<rect x="24" y="${78 + i * 62}" width="350" height="50" rx="10" fill="none" stroke="#e5a00d"/><text x="40" y="${108 + i * 62}" font-size="14">${["Movie night", "The next episode"][i]}</text>`).join("")}</g></svg>`);
  }
  const registered = { ...manifest, translations: mediaTranslations, entry: `/media/providers/plex/widgets/${slug}/widget.js`, runtime: "prebuilt_bundle",
    previews: { light: `/media/providers/plex/widgets/${slug}/preview-light.svg`, dark: `/media/providers/plex/widgets/${slug}/preview-dark.svg` },
    host_bridge: { protocol: "piphi.widget.host", version: "1", events: ["ready", "resize"] } };
  integration.ui.widget_packages = integration.ui.widget_packages.filter((pkg) => pkg.id !== manifest.id);
  integration.ui.widget_packages.push(registered);
  if (slug === "recently-added") await writeFile(new URL("experiences/plex-media/assets/live-media.js", root), bytes);
}
await writeFile(new URL("manifest.json", root), JSON.stringify(integration, null, 2) + "\n");
