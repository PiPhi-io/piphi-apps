package app

import (
	"errors"
	"testing"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

func TestIsAtmotubeDiscoveryMatchUsesServiceFlag(t *testing.T) {
	device := atmotube.DiscoveredDevice{
		Name:               "Unknown BLE Sensor",
		HasAtmotubeService: true,
	}

	if !isAtmotubeDiscoveryMatch(device) {
		t.Fatalf("expected device with Atmotube service flag to match")
	}
}

func TestIsAtmotubeDiscoveryMatchRejectsNonAtmotubeDevice(t *testing.T) {
	device := atmotube.DiscoveredDevice{
		Name:               "Weather Beacon",
		HasAtmotubeService: false,
	}

	if isAtmotubeDiscoveryMatch(device) {
		t.Fatalf("expected non-Atmotube device to be rejected")
	}
}

func TestFirstNonEmptyReturnsFirstValue(t *testing.T) {
	got := firstNonEmpty("", "integration-a", "integration-b")
	if got != "integration-a" {
		t.Fatalf("expected first non-empty value, got %q", got)
	}
}

func TestFirstNonEmptyReturnsEmptyWhenAllValuesEmpty(t *testing.T) {
	if got := firstNonEmpty("", "", ""); got != "" {
		t.Fatalf("expected empty string, got %q", got)
	}
}

func TestAppendLocalEventStoresDeviceMetadata(t *testing.T) {
	app := NewWithOptions(&fakeBLEClient{}, false)
	entry := atmotube.DeviceEntry{
		ConfigID:      "bedroom",
		DeviceID:      "device-1",
		ContainerID:   "container-1",
		IntegrationID: "integration-1",
	}

	app.appendLocalEvent("atmotube.test", entry, map[string]any{"reason": "unit-test"})

	events := app.registry.RecentEvents()
	if len(events) != 1 {
		t.Fatalf("expected one event, got %d", len(events))
	}
	event := events[0]
	if event["device_id"] != "device-1" {
		t.Fatalf("expected device_id to be captured, got %#v", event["device_id"])
	}
	payload, ok := event["payload"].(map[string]any)
	if !ok {
		t.Fatalf("expected payload to be a map, got %#v", event["payload"])
	}
	if payload["reason"] != "unit-test" {
		t.Fatalf("expected payload reason to be preserved, got %#v", payload["reason"])
	}
}

func TestRemoveConfigCancelsTrackedPoller(t *testing.T) {
	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	cancelled := false
	app.pollers["bedroom"] = func() { cancelled = true }
	app.registry.Set("bedroom", atmotube.DeviceEntry{
		ConfigID: "bedroom",
		DeviceID: "device-1",
		Address:  "11:22:33:AA:BB:CC",
	})

	removed := app.removeConfig("bedroom")

	if !removed {
		t.Fatalf("expected removeConfig to report removal")
	}
	if !cancelled {
		t.Fatalf("expected poller cancel function to run")
	}
	if _, ok := app.pollers["bedroom"]; ok {
		t.Fatalf("expected poller entry to be removed")
	}
}

func TestPollOnceAppendsErrorEventOnReadFailure(t *testing.T) {
	app := NewWithOptions(&fakeBLEClient{readErr: errors.New("bluetooth offline")}, false)
	entry := atmotube.DeviceEntry{
		ConfigID: "bedroom",
		DeviceID: "device-1",
		Address:  "11:22:33:AA:BB:CC",
	}

	app.pollOnce(entry)

	events := app.registry.RecentEvents()
	if len(events) != 1 {
		t.Fatalf("expected one error event, got %d", len(events))
	}
	if events[0]["event_type"] != "atmotube.poll.error" {
		t.Fatalf("expected poll error event, got %#v", events[0]["event_type"])
	}
}
