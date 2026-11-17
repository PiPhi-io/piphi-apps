import { loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy, writeIdentityCandidates } from "./identity.js";
import { renderMosquittoConfig, writeMosquittoConfig } from "./mosquitto.js";

async function main(): Promise<void> {
  const config = loadBrokerConfig();
  const shouldPrint = process.argv.includes("--print");

  if (shouldPrint) {
    process.stdout.write(renderMosquittoConfig(config));
    return;
  }

  const policy = await loadIdentityPolicy(config);
  await writeIdentityCandidates(config, policy);
  if (!process.argv.includes("--credentials-only")) await writeMosquittoConfig(config);
  process.stdout.write(
    JSON.stringify(
      {
        status: "ok",
        configOutputPath: config.configOutputPath,
        port: config.port,
        allowAnonymous: config.allowAnonymous,
        persistence: config.persistence,
        principalCount: policy.principals.length,
      },
      null,
      2,
    ) + "\n",
  );
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(message + "\n");
  process.exitCode = 1;
});
