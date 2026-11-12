const STATUSES = new Set(["loading", "live", "stale", "offline", "reconnecting", "denied", "error"]);
export function normalizeStatus(value) { return STATUSES.has(value) ? value : "error"; }
export function normalizeEvents(input, { now = new Date(), days = 7 } = {}) {
  const startWindow = now.getTime();
  const endWindow = startWindow + Math.max(1, Math.min(31, Number(days) || 7)) * 86400000;
  return (Array.isArray(input) ? input : []).flatMap((event, index) => {
    if (!event || typeof event !== "object") return [];
    const start = parseDate(event.start), end = parseDate(event.end ?? event.start);
    if (!start || !end || end < start || end.getTime() < startWindow || start.getTime() > endWindow) return [];
    return [{id:String(event.id ?? `${start.toISOString()}-${index}`),title:cleanText(event.title ?? event.summary ?? "Untitled event",160),calendar:cleanText(event.calendar_name ?? event.calendar ?? "Calendar",80),location:cleanText(event.location ?? "",160),start,end,allDay:Boolean(event.all_day ?? isDateOnly(event.start)),active:Boolean(event.active)}];
  }).sort((a,b) => a.start - b.start || a.title.localeCompare(b.title));
}
export function groupEvents(events, locale = "en", timezone) {
  const formatter = new Intl.DateTimeFormat(locale,{weekday:"long",month:"short",day:"numeric",timeZone:timezone||undefined});
  return events.reduce((groups,event) => { const label=formatter.format(event.start); const last=groups.at(-1); if(last?.label===label) last.events.push(event); else groups.push({label,events:[event]}); return groups; },[]);
}
export function formatEventTime(event, locale="en", timezone, allDayLabel="All day") { if(event.allDay) return allDayLabel; const f=new Intl.DateTimeFormat(locale,{hour:"numeric",minute:"2-digit",timeZone:timezone||undefined}); return `${f.format(event.start)}–${f.format(event.end)}`; }
export function lifecycleMessage(status,count,labels){ if(status==="live"&&count===0)return labels.empty;if(status==="loading")return labels.waiting;return status; }
function parseDate(value){const parsed=value instanceof Date?new Date(value):new Date(String(value??""));return Number.isFinite(parsed.getTime())?parsed:null;}
function isDateOnly(value){return /^\d{4}-\d{2}-\d{2}$/.test(String(value??""));}
function cleanText(value,max){return String(value).replace(/[\u0000-\u001f\u007f]/g," ").trim().slice(0,max);}
