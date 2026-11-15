import { loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy, writeIdentityFiles } from "./identity.js";
import { renderMosquittoConfig, writeMosquittoConfig } from "./mosquitto.js";

async function main(): Promise<void> {
  const config = loadBrokerConfig();
  const shouldPrint = process.argv.includes("--print");

  if (shouldPrint) {
    process.stdout.write(renderMosquittoConfig(config));
    return;
  }

  const policy = await loadIdentityPolicy(config);
  await writeIdentityFiles(config, policy);
  if (!process.argv.includes("--credentials-only")) await writeMosquittoConfig(config);
  process.stdout.write(
    JSON.stringify(
      {
        status: "ok",
        configOutputPath: config.configOutputPath,
        port: config.port,
        allowAnonymous: config.allowAnonymous,
        persistence: config.persistence,
        topicPrefix: config.topicPrefix,
        principalCount: policy.principals.length,
        policyDigest: policy.sourceDigest,
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
