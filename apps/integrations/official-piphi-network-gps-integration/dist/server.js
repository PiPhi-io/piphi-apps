import express from "express";
import { fileURLToPath } from "node:url";
import expressWinston from "express-winston";
import winston from "winston";
import { router as healthRouter } from "./routes/health/health.routes.js";
import { uischemaRouter } from "./routes/uischema/uischema.routes.js";
import { router as configRouter } from "./routes/config/config.routes.js";
import { router as discoveryRouter } from "./routes/discovery/router.js";
import { router as deconfigureRouter } from "./routes/deconfigure/deconfigure.routes.js";
import { router as stateRouter } from "./routes/state/state.routes.js";
import { router as entitiesRouter } from "./routes/entities/entities.routes.js";
import { router as diagnosticsRouter } from "./routes/diagnostics/diagnostics.routes.js";
import { router as eventsRouter } from "./routes/events/events.routes.js";
import { router as commandRouter } from "./routes/command/command.routes.js";
export const app = express();
app.use(express.json());
export const logger = winston.createLogger({
    level: "info",
    transports: [
        new winston.transports.Console({
            format: winston.format.combine(winston.format.colorize(), winston.format.timestamp({ format: "YYYY-MM-DD HH:mm:ss" }), winston.format.printf(({ level, message, timestamp }) => {
                return `[${timestamp}] ${level}: ${message}`;
            })),
        }),
    ],
});
app.use(expressWinston.logger({
    winstonInstance: logger,
    meta: true,
    msg: "HTTP {{req.method}} {{req.url}}",
    expressFormat: true,
    colorize: true,
}));
app.use("/health", healthRouter);
app.use(uischemaRouter);
app.use(configRouter);
app.use(discoveryRouter);
app.use(deconfigureRouter);
app.use(stateRouter);
app.use(entitiesRouter);
app.use(diagnosticsRouter);
app.use(eventsRouter);
app.use(commandRouter);
const port = Number(process.env.PORT || 3080);
if (process.argv[1] === fileURLToPath(import.meta.url)) {
    app.listen(port, () => {
        logger.info(`Server started on port ${port}`);
    });
}
