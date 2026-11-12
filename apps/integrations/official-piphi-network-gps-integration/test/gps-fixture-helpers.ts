function buildSentence(body: string): string {
  const checksum = [...body]
    .reduce((accumulator, character) => accumulator ^ character.charCodeAt(0), 0)
    .toString(16)
    .toUpperCase()
    .padStart(2, "0");
  return `$${body}*${checksum}`;
}

function formatNmeaDate(date: Date): string {
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const year = String(date.getUTCFullYear()).slice(-2);
  return `${day}${month}${year}`;
}

function formatNmeaTime(date: Date): string {
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  const seconds = String(date.getUTCSeconds()).padStart(2, "0");
  return `${hours}${minutes}${seconds}`;
}

export function createUtcDateWithOffset(secondsOffset = 0): Date {
  const date = new Date();
  date.setUTCMilliseconds(0);
  date.setUTCSeconds(date.getUTCSeconds() + secondsOffset);
  return date;
}

export function buildRmcSentence(date: Date, status = "A"): string {
  return buildSentence(
    `GPRMC,${formatNmeaTime(date)},${status},4807.038,N,01131.000,E,022.4,084.4,${formatNmeaDate(date)},003.1,W`,
  );
}

export function buildGgaSentence(date: Date, fixQuality = 1): string {
  const latitude = fixQuality === 0 ? "" : "4807.038";
  const northSouth = fixQuality === 0 ? "" : "N";
  const longitude = fixQuality === 0 ? "" : "01131.000";
  const eastWest = fixQuality === 0 ? "" : "E";
  const satellites = fixQuality === 0 ? "00" : "08";
  const hdop = fixQuality === 0 ? "99.9" : "0.9";
  const altitude = fixQuality === 0 ? "" : "545.4";
  return buildSentence(
    `GPGGA,${formatNmeaTime(date)},${latitude},${northSouth},${longitude},${eastWest},${fixQuality},${satellites},${hdop},${altitude},M,46.9,M,,`,
  );
}

export function buildGsaSentence(fixMode = "3", hdop = "1.5", pdop = "1.8", vdop = "0.9"): string {
  return buildSentence(`GPGSA,A,${fixMode},04,05,09,12,24,25,29,31,,,,${pdop},${vdop},${hdop}`);
}

export function assertApproximate(actual: number, expected: number, epsilon = 0.000001): void {
  if (Math.abs(actual - expected) > epsilon) {
    throw new Error(`expected ${actual} to be within ${epsilon} of ${expected}`);
  }
}
