package atmotube

import (
	"encoding/binary"
	"fmt"
	"time"

	"tinygo.org/x/bluetooth"
)

var (
	ServiceUUID = mustParseUUID(ServiceUUIDString)
	VOCUUID     = mustParseUUID(VOCUUIDString)
	BMEUUID     = mustParseUUID(BMEUUIDString)
	StatusUUID  = mustParseUUID(StatusUUIDString)
	PMUUID      = mustParseUUID(PMUUIDString)
)

func mustParseUUID(value string) bluetooth.UUID {
	uuid, err := bluetooth.ParseUUID(value)
	if err != nil {
		panic(err)
	}
	return uuid
}

func parseVOC(data []byte) (uint16, error) {
	if len(data) < 2 {
		return 0, fmt.Errorf("invalid VOC payload length: %d", len(data))
	}
	return binary.LittleEndian.Uint16(data[:2]), nil
}

func parseBME(data []byte) (humidity float64, temperatureC float64, pressureMbar float64, err error) {
	if len(data) < 8 {
		return 0, 0, 0, fmt.Errorf("invalid BME payload length: %d", len(data))
	}
	humidity = float64(data[0])
	pressureMbar = float64(binary.LittleEndian.Uint32(data[2:6])) / 100
	temperatureRaw := int16(binary.LittleEndian.Uint16(data[6:8]))
	temperatureC = float64(temperatureRaw) / 100
	return humidity, temperatureC, pressureMbar, nil
}

func parseStatus(data []byte) (infoByte uint8, batteryPercent uint8, err error) {
	if len(data) < 2 {
		return 0, 0, fmt.Errorf("invalid status payload length: %d", len(data))
	}
	return data[0], data[1], nil
}

func parsePM(data []byte) (pm1 float64, pm25 float64, pm4 float64, pm10 float64, err error) {
	if len(data) < 12 {
		return 0, 0, 0, 0, fmt.Errorf("invalid PM payload length: %d", len(data))
	}
	pm1 = float64(parseUint24LE(data[0:3])) / 100
	pm25 = float64(parseUint24LE(data[3:6])) / 100
	pm10 = float64(parseUint24LE(data[6:9])) / 100
	pm4 = float64(parseUint24LE(data[9:12])) / 100
	return pm1, pm25, pm4, pm10, nil
}

func parseUint24LE(data []byte) uint32 {
	if len(data) < 3 {
		return 0
	}
	return uint32(data[0]) | uint32(data[1])<<8 | uint32(data[2])<<16
}

func parseAdvertisement(manufacturerData []byte) map[string]any {
	if len(manufacturerData) < 12 {
		return nil
	}
	voc := binary.LittleEndian.Uint16(manufacturerData[0:2])
	deviceID := binary.LittleEndian.Uint16(manufacturerData[2:4])
	humidity := manufacturerData[4]
	temperature := manufacturerData[5]
	pressure := binary.LittleEndian.Uint32(manufacturerData[6:10])
	info := manufacturerData[10]
	battery := manufacturerData[11]

	return map[string]any{
		"sampled_at":          time.Now().UTC().Format(time.RFC3339),
		"voc_ppb":             voc,
		"humidity_percent":    humidity,
		"temperature_c":       float64(temperature),
		"pressure_mbar":       float64(pressure) / 100,
		"battery_percent":     battery,
		"info_byte":           info,
		"broadcast_device_id": deviceID,
	}
}
