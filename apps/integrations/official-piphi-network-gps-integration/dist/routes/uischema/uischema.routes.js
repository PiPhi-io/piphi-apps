import express from "express";
import { getGPSDevicePaths } from "../../lib/gps.js";
export const uischemaRouter = express.Router();
const baseSchema = {
    title: "USB GPS Integration Configuration",
    description: "Configuration for USB GPS and NMEA serial integrations.",
    type: "object",
    required: ["path"],
    properties: {
        path: {
            type: "string",
            title: "GPS Device Path",
            description: "USB GPS or NMEA serial device path/address",
            enum: [],
            enumNames: [],
            errorMessage: "Please select a device before continuing",
        },
    },
};
async function handleUiSchema(_req, res) {
    const devices = (await getGPSDevicePaths());
    const schema = {
        ...baseSchema,
        properties: {
            ...baseSchema.properties,
            path: {
                ...baseSchema.properties.path,
                enum: devices.map((device) => device.path),
                enumNames: devices.map((device) => `${device.name} [${device.confidence}]`),
            },
        },
    };
    res.json({
        schema,
        uiSchema: {
            path: {
                "ui:widget": "select",
            },
        },
        devices,
    });
}
uischemaRouter.get("/ui", handleUiSchema);
uischemaRouter.get("/ui-config", handleUiSchema);
