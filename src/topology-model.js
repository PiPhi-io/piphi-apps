const MAX_NODES = 500;
const MAX_LINKS = 4000;

export function normalizeTopology(input) {
  const state = unwrapState(input);
  const source = state?.zigbee_network_topology ?? state?.topology ?? state;
  const rawNodes = Array.isArray(source?.nodes) ? source.nodes.slice(0, MAX_NODES) : [];
  const rawLinks = Array.isArray(source?.links) ? source.links.slice(0, MAX_LINKS) : [];
  const nodes = rawNodes.map(normalizeNode).filter(Boolean);
  const ids = new Set(nodes.map((node) => node.id));
  const links = rawLinks.map(normalizeLink).filter((link) => link && ids.has(link.source) && ids.has(link.target));
  return {
    nodes,
    links,
    status: cleanText(source?.status, 32) || "ok",
    collectedAt: validDate(source?.collected_at ?? source?.collectedAt),
    routesIncluded: source?.routes_included === true || source?.routesIncluded === true,
  };
}

export function layoutTopology(topology, width = 760, height = 420) {
  const nodes = [...topology.nodes].sort(compareNodes);
  if (!nodes.length) return { nodes: [], links: [] };
  const center = { x: width / 2, y: height / 2 };
  const coordinator = nodes.find((node) => node.type === "coordinator") ?? nodes[0];
  const routers = nodes.filter((node) => node !== coordinator && node.type === "router");
  const endDevices = nodes.filter((node) => node !== coordinator && node.type !== "router");
  const positions = new Map([[coordinator.id, center]]);
  placeRing(routers, center, Math.min(width, height) * 0.24, positions, -Math.PI / 2);
  placeRing(endDevices, center, Math.min(width, height) * 0.43, positions, -Math.PI / 2 + 0.18);
  const positionedNodes = nodes.map((node) => ({ ...node, ...(positions.get(node.id) ?? center) }));
  const byId = new Map(positionedNodes.map((node) => [node.id, node]));
  const links = topology.links
    .map((link) => ({ ...link, sourceNode: byId.get(link.source), targetNode: byId.get(link.target) }))
    .filter((link) => link.sourceNode && link.targetNode);
  return { nodes: positionedNodes, links };
}

export function lifecycleMessage(status, topology, messages) {
  if (status === "loading" || status === "reconnecting") return messages.loading;
  if (status === "denied") return messages.denied;
  if (status === "error") return messages.error;
  if (!topology.nodes.length) return messages.empty;
  if (status === "offline") return messages.offline;
  if (status === "stale") return messages.stale;
  return messages.live;
}

export function normalizeLifecycle(value) {
  const status = String(value || "loading").toLowerCase();
  return ["loading", "live", "stale", "offline", "reconnecting", "denied", "error"].includes(status)
    ? status
    : "error";
}

export function linkQualityTone(value) {
  if (!Number.isFinite(value)) return "unknown";
  if (value >= 170) return "strong";
  if (value >= 85) return "fair";
  return "weak";
}

function normalizeNode(node, index) {
  if (!node || typeof node !== "object") return null;
  const id = cleanText(node.id ?? node.ieee_address ?? node.ieeeAddr ?? node.network_address, 256) || `node-${index}`;
  return {
    id,
    name: cleanText(node.friendly_name ?? node.friendlyName, 128) || id,
    type: normalizeType(node.type),
    ieeeAddress: cleanText(node.ieee_address ?? node.ieeeAddr, 256),
    networkAddress: boundedNumber(node.network_address ?? node.networkAddress, 0, 65535),
    manufacturer: cleanText(node.manufacturer ?? node.manufacturerName, 128),
    model: cleanText(node.model ?? node.modelID, 128),
  };
}

function normalizeLink(link) {
  if (!link || typeof link !== "object") return null;
  const source = endpointId(link.source);
  const target = endpointId(link.target);
  if (!source || !target) return null;
  return {
    source,
    target,
    linkQuality: boundedNumber(link.link_quality ?? link.linkquality ?? link.linkQuality, 0, 255),
    depth: boundedNumber(link.depth, 0, 255),
    routes: Array.isArray(link.routes)
      ? link.routes.slice(0, 128).map((value) => boundedNumber(value, 0, 65535)).filter(Number.isFinite)
      : [],
  };
}

function endpointId(value) {
  if (value && typeof value === "object") value = value.id ?? value.ieee_address ?? value.ieeeAddr ?? value.networkAddress;
  return cleanText(value, 256);
}

function unwrapState(input) {
  let value = input?.primaryState ?? input?.state ?? input?.value ?? input ?? {};
  if (value?.state && typeof value.state === "object") value = value.state;
  return value;
}

function normalizeType(value) {
  const type = cleanText(value, 32)?.toLowerCase();
  if (type === "coordinator" || type === "router") return type;
  return "end-device";
}

function cleanText(value, limit) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, limit);
}

function boundedNumber(value, minimum, maximum) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= minimum && number <= maximum ? number : null;
}

function validDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function compareNodes(left, right) {
  const order = { coordinator: 0, router: 1, "end-device": 2 };
  return order[left.type] - order[right.type] || left.name.localeCompare(right.name);
}

function placeRing(nodes, center, radius, positions, offset) {
  nodes.forEach((node, index) => {
    const angle = offset + (Math.PI * 2 * index) / Math.max(nodes.length, 1);
    positions.set(node.id, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius });
  });
}
