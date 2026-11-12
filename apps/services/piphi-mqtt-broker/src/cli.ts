import { loadBrokerConfig } from "./config.js";
import { renderMosquittoConfig, writeMosquittoConfig } from "./mosquitto.js";

async function main(): Promise<void> {
  const config = loadBrokerConfig();
  const shouldPrint = process.argv.includes("--print");

  if (shouldPrint) {
    process.stdout.write(renderMosquittoConfig(config));
    return;
  }

  await writeMosquittoConfig(config);
  process.stdout.write(
    JSON.stringify(
      {
        status: "ok",
        configOutputPath: config.configOutputPath,
        port: config.port,
        allowAnonymous: config.allowAnonymous,
        persistence: config.persistence,
        topicPrefix: config.topicPrefix,
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

