package atmotube

import (
	"encoding/binary"
	"testing"
)

func TestDeviceConfigNormalizeTrimsAndDefaultsFields(t *testing.T) {
	config := DeviceConfig{
		Address: " 11:22:33:aa:bb:cc ",
		Alias:   " Bedroom ",
	}

	normalized := config.Normalize()

	if normalized.Address != "11:22:33:AA:BB:CC" {
		t.Fatalf("expected uppercased address, got %q", normalized.Address)
	}
	if normalized.Alias != "Bedroom" {
		t.Fatalf("expected trimmed alias, got %q", normalized.Alias)
	}
	if normalized.ID != "11:22:33:AA:BB:CC" {
		t.Fatalf("expected default config ID from address, got %q", normalized.ID)
	}
	if normalized.DeviceID != normalized.ID {
		t.Fatalf("expected default device ID to match ID, got %q", normalized.DeviceID)
	}
	if normalized.PollIntervalSeconds != DefaultPollIntervalSeconds {
		t.Fatalf("expected default poll interval %d, got %d", DefaultPollIntervalSeconds, normalized.PollIntervalSeconds)
	}
}

func TestDeviceConfigPollIntervalUsesNormalizedDefaults(t *testing.T) {
	config := DeviceConfig{}
	if got := config.PollInterval().Seconds(); int(got) != DefaultPollIntervalSeconds {
		t.Fatalf("expected poll interval seconds %d, got %.0f", DefaultPollIntervalSeconds, got)
	}
}

func TestDeviceConfigGetRuntimeConfigIDUsesNormalizedID(t *testing.T) {
	config := DeviceConfig{Address: "11:22:33:aa:bb:cc"}
	if got := config.GetRuntimeConfigID(); got != "11:22:33:AA:BB:CC" {
		t.Fatalf("expected normalized runtime config ID, got %q", got)
	}
}

func TestParseVOCValidPayload(t *testing.T) {
	value, err := parseVOC([]byte{0x34, 0x12})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if value != 0x1234 {
		t.Fatalf("expected 0x1234, got %#x", value)
	}
}

func TestParseVOCRejectsShortPayload(t *testing.T) {
	if _, err := parseVOC([]byte{0x01}); err == nil {
		t.Fatalf("expected invalid payload error")
	}
}

func TestParseBMEValidPayload(t *testing.T) {
	payload := make([]byte, 8)
	payload[0] = 45
	binary.LittleEndian.PutUint32(payload[2:6], 101325)
	binary.LittleEndian.PutUint16(payload[6:8], uint16(int16(2234)))

	humidity, temperatureC, pressureMbar, err := parseBME(payload)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if humidity != 45 {
		t.Fatalf("expected humidity 45, got %.2f", humidity)
	}
	if temperatureC != 22.34 {
		t.Fatalf("expected temperature 22.34, got %.2f", temperatureC)
	}
	if pressureMbar != 1013.25 {
		t.Fatalf("expected pressure 1013.25, got %.2f", pressureMbar)
	}
}

func TestParseBMERejectsShortPayload(t *testing.T) {
	if _, _, _, err := parseBME([]byte{1, 2, 3}); err == nil {
		t.Fatalf("expected invalid payload error")
	}
}

func TestParseStatusValidPayload(t *testing.T) {
	infoByte, batteryPercent, err := parseStatus([]byte{0x05, 0x64})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if infoByte != 0x05 || batteryPercent != 0x64 {
		t.Fatalf("unexpected status parse result: info=%d battery=%d", infoByte, batteryPercent)
	}
}

func TestParseStatusRejectsShortPayload(t *testing.T) {
	if _, _, err := parseStatus([]byte{0x01}); err == nil {
		t.Fatalf("expected invalid payload error")
	}
}

func TestParsePMValidPayload(t *testing.T) {
	payload := []byte{
		0x64, 0x00, 0x00,
		0xC8, 0x00, 0x00,
		0x2C, 0x01, 0x00,
		0x90, 0x01, 0x00,
	}

	pm1, pm25, pm4, pm10, err := parsePM(payload)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pm1 != 1.00 || pm25 != 2.00 || pm10 != 3.00 || pm4 != 4.00 {
		t.Fatalf("unexpected PM values: pm1=%.2f pm25=%.2f pm4=%.2f pm10=%.2f", pm1, pm25, pm4, pm10)
	}
}

func TestParsePMRejectsShortPayload(t *testing.T) {
	if _, _, _, _, err := parsePM([]byte{1, 2, 3}); err == nil {
		t.Fatalf("expected invalid payload error")
	}
}

func TestParseUint24LEReturnsZeroForShortPayload(t *testing.T) {
	if value := parseUint24LE([]byte{0x01, 0x02}); value != 0 {
		t.Fatalf("expected zero for short payload, got %d", value)
	}
}

func TestParseUint24LEParsesLittleEndianValue(t *testing.T) {
	if value := parseUint24LE([]byte{0x01, 0x02, 0x03}); value != 0x030201 {
		t.Fatalf("expected 0x030201, got %#x", value)
	}
}

func TestParseAdvertisementReturnsNilForShortPayload(t *testing.T) {
	if parsed := parseAdvertisement([]byte{1, 2, 3}); parsed != nil {
		t.Fatalf("expected nil advertisement parse result, got %#v", parsed)
	}
}

func TestParseAdvertisementParsesFields(t *testing.T) {
	payload := make([]byte, 12)
	binary.LittleEndian.PutUint16(payload[0:2], 220)
	binary.LittleEndian.PutUint16(payload[2:4], 42)
	payload[4] = 51
	payload[5] = 23
	binary.LittleEndian.PutUint32(payload[6:10], 100875)
	payload[10] = 3
	payload[11] = 88

	parsed := parseAdvertisement(payload)

	if parsed == nil {
		t.Fatalf("expected parsed advertisement")
	}
	if parsed["voc_ppb"] != uint16(220) {
		t.Fatalf("expected VOC 220, got %#v", parsed["voc_ppb"])
	}
	if parsed["broadcast_device_id"] != uint16(42) {
		t.Fatalf("expected broadcast device id 42, got %#v", parsed["broadcast_device_id"])
	}
	if parsed["battery_percent"] != uint8(88) {
		t.Fatalf("expected battery 88, got %#v", parsed["battery_percent"])
	}
}
