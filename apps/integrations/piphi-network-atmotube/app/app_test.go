package app

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

type fakeBLEClient struct {
	discovered []atmotube.DiscoveredDevice
	reading    atmotube.Reading
	scanErr    error
	readErr    error
	scanCalls  int
	lastFilter string
	lastTimeout time.Duration
}

func (f *fakeBLEClient) Scan(ctx context.Context, timeout time.Duration, addressFilter string) ([]atmotube.DiscoveredDevice, error) {
	f.scanCalls++
	f.lastFilter = addressFilter
	f.lastTimeout = timeout
	return f.discovered, f.scanErr
}

func (f *fakeBLEClient) ReadSnapshot(address string) (atmotube.Reading, error) {
	return f.reading, f.readErr
}

func sampleReading() atmotube.Reading {
	return atmotube.Reading{
		SampledAt:       "2026-04-06T20:00:00Z",
		VOCPPB:          120,
		VOCPPM:          0.12,
		HumidityPercent: 45.2,
		TemperatureC:    22.4,
		PressureMbar:    1013.2,
		BatteryPercent:  87,
		StatusByte:      1,
		InfoByte:        2,
		PM1UGM3:         1.1,
		PM25UGM3:        2.3,
		PM4UGM3:         3.4,
		PM10UGM3:        4.5,
	}
}

func TestDiscoverReturnsBLEDevices(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		discovered: []atmotube.DiscoveredDevice{
			{
				ID:                 "11:22:33:AA:BB:CC",
				DeviceID:           "11:22:33:AA:BB:CC",
				Address:            "11:22:33:AA:BB:CC",
				Name:               "Atmotube Pro",
				RSSI:               -48,
				HasAtmotubeService: true,
				Broadcast: map[string]any{
					"voc_ppb": 220,
				},
			},
		},
	}

	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/discover", bytes.NewReader([]byte(`{"inputs":{"address":"11:22:33:AA:BB:CC"}}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}

	if len(response.Devices) != 1 {
		t.Fatalf("expected one discovered device, got %d", len(response.Devices))
	}
	if response.Devices[0].Address != "11:22:33:AA:BB:CC" {
		t.Fatalf("unexpected discovered address: %s", response.Devices[0].Address)
	}
	if !response.Devices[0].HasAtmotubeService {
		t.Fatalf("expected discovered device to advertise the Atmotube service")
	}
}

func TestDiscoverFiltersOutNonAtmotubeDevices(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		discovered: []atmotube.DiscoveredDevice{
			{
				ID:                 "11:22:33:AA:BB:CC",
				DeviceID:           "11:22:33:AA:BB:CC",
				Address:            "11:22:33:AA:BB:CC",
				Name:               "ATMOTUBE PRO",
				RSSI:               -48,
				HasAtmotubeService: true,
			},
			{
				ID:                 "22:33:44:BB:CC:DD",
				DeviceID:           "22:33:44:BB:CC:DD",
				Address:            "22:33:44:BB:CC:DD",
				Name:               "Random BLE Sensor",
				RSSI:               -55,
				HasAtmotubeService: false,
			},
		},
	}

	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}

	if len(response.Devices) != 1 {
		t.Fatalf("expected one filtered device, got %d", len(response.Devices))
	}
	if response.Devices[0].Name != "ATMOTUBE PRO" {
		t.Fatalf("unexpected filtered device name: %s", response.Devices[0].Name)
	}
}

func TestDiscoverKeepsServiceMatchWithoutAtmotubeName(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		discovered: []atmotube.DiscoveredDevice{
			{
				ID:                 "33:44:55:CC:DD:EE",
				DeviceID:           "33:44:55:CC:DD:EE",
				Address:            "33:44:55:CC:DD:EE",
				Name:               "",
				RSSI:               -60,
				HasAtmotubeService: true,
			},
		},
	}

	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}

	if len(response.Devices) != 1 {
		t.Fatalf("expected service-based match to remain, got %d devices", len(response.Devices))
	}
	if response.Devices[0].Address != "33:44:55:CC:DD:EE" {
		t.Fatalf("unexpected retained address: %s", response.Devices[0].Address)
	}
}

func TestConfigSyncAppliesAndRemovesConfigs(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		reading: sampleReading(),
	}

	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	firstConfig := atmotube.DeviceConfig{
		Address: "11:22:33:AA:BB:CC",
		Alias:   "Bedroom",
	}
	firstConfig.ID = "bedroom"
	firstConfig.DeviceID = "bedroom"
	firstConfig.ContainerID = "container-1"
	firstConfig.IntegrationID = "integration-1"

	_, err := app.applyConfig(firstConfig)
	if err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	secondConfig := atmotube.DeviceConfig{
		Address:             "AA:BB:CC:DD:EE:FF",
		Alias:               "Office",
		PollIntervalSeconds: 45,
	}
	secondConfig.ID = "office"
	secondConfig.DeviceID = "office"
	secondConfig.ContainerID = "container-1"
	secondConfig.IntegrationID = "integration-1"

	generation := 7
	payload := map[string]any{
		"container_id":   "container-1",
		"integration_id": "integration-1",
		"generation":     generation,
		"configs":        []atmotube.DeviceConfig{secondConfig},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}

	request := httptest.NewRequest(http.MethodPost, "/config/sync", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Container-Id", "container-1")
	request.Header.Set("X-PiPhi-Integration-Token", "test-token")

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		OK               bool     `json:"ok"`
		AppliedConfigIDs []string `json:"applied_config_ids"`
		RemovedConfigIDs []string `json:"removed_config_ids"`
		SkippedConfigIDs []string `json:"skipped_config_ids"`
		Generation       *int     `json:"generation"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}

	if !response.OK {
		t.Fatalf("expected ok response")
	}
	if len(response.AppliedConfigIDs) != 1 || response.AppliedConfigIDs[0] != "office" {
		t.Fatalf("unexpected applied config ids: %#v", response.AppliedConfigIDs)
	}
	if len(response.RemovedConfigIDs) != 1 || response.RemovedConfigIDs[0] != "bedroom" {
		t.Fatalf("unexpected removed config ids: %#v", response.RemovedConfigIDs)
	}
	if len(response.SkippedConfigIDs) != 0 {
		t.Fatalf("unexpected skipped config ids: %#v", response.SkippedConfigIDs)
	}
	if response.Generation == nil || *response.Generation != generation {
		t.Fatalf("unexpected generation: %#v", response.Generation)
	}

	if _, ok := app.registry.Get("bedroom"); ok {
		t.Fatalf("expected stale config to be removed from registry")
	}
	entry, ok := app.registry.Get("office")
	if !ok {
		t.Fatalf("expected synced config to exist in registry")
	}
	if entry.Address != "AA:BB:CC:DD:EE:FF" {
		t.Fatalf("unexpected synced address: %s", entry.Address)
	}
	if len(app.registry.RecentEvents()) == 0 {
		t.Fatalf("expected config lifecycle events to be recorded")
	}
}

func TestDiscoverReturnsEmptyWhenNoAtmotubeMatches(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		discovered: []atmotube.DiscoveredDevice{
			{
				ID:                 "22:33:44:BB:CC:DD",
				DeviceID:           "22:33:44:BB:CC:DD",
				Address:            "22:33:44:BB:CC:DD",
				Name:               "Random BLE Sensor",
				RSSI:               -55,
				HasAtmotubeService: false,
			},
		},
	}

	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()

	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(response.Devices) != 0 {
		t.Fatalf("expected no discovered devices, got %d", len(response.Devices))
	}
}

func TestHealthReportsActiveConfigCount(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID:          "bedroom",
			DeviceID:    "bedroom",
			ContainerID: "container-1",
		},
		Address: "11:22:33:AA:BB:CC",
		Alias:   "Bedroom",
	}
	if _, err := app.applyConfig(config); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/health", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	metadata := response["metadata"].(map[string]any)
	if metadata["active_configs"].(float64) != 1 {
		t.Fatalf("expected active_configs=1, got %#v", metadata["active_configs"])
	}
}

func TestDiagnosticsReportsRecentEventCountAndConfigIDs(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID:            "bedroom",
			DeviceID:      "bedroom",
			ContainerID:   "container-1",
			IntegrationID: integrationID,
		},
		Address: "11:22:33:AA:BB:CC",
		Alias:   "Bedroom",
	}
	entry, err := app.applyConfig(config)
	if err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}
	app.appendLocalEvent("atmotube.manual.note", entry, map[string]any{"message": "hello"})

	request := httptest.NewRequest(http.MethodGet, "/diagnostics", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	diagnostics := response["diagnostics"].(map[string]any)
	if diagnostics["recent_event_count"].(float64) < 2 {
		t.Fatalf("expected recent_event_count >= 2, got %#v", diagnostics["recent_event_count"])
	}
	configIDs := diagnostics["active_config_ids"].([]any)
	if len(configIDs) != 1 || configIDs[0].(string) != "bedroom" {
		t.Fatalf("unexpected active_config_ids: %#v", configIDs)
	}
}

func TestUISchemaContainsAddressAndPollInterval(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/ui", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	schema := response["schema"].(map[string]any)
	properties := schema["properties"].(map[string]any)
	if _, ok := properties["address"]; !ok {
		t.Fatalf("expected address field in ui schema")
	}
	if _, ok := properties["poll_interval_seconds"]; !ok {
		t.Fatalf("expected poll_interval_seconds field in ui schema")
	}
}

func TestEntitiesReturnsConfiguredEntries(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID:          "bedroom",
			DeviceID:    "bedroom",
			ContainerID: "container-1",
		},
		Address: "11:22:33:AA:BB:CC",
		Alias:   "Bedroom",
	}
	if _, err := app.applyConfig(config); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/entities", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Entities []map[string]any `json:"entities"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(response.Entities) != 1 {
		t.Fatalf("expected one entity, got %d", len(response.Entities))
	}
	if response.Entities[0]["alias"].(string) != "Bedroom" {
		t.Fatalf("unexpected alias: %#v", response.Entities[0]["alias"])
	}
}

func TestStateReturnsEntriesAndSnapshots(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID:          "bedroom",
			DeviceID:    "bedroom",
			ContainerID: "container-1",
		},
		Address: "11:22:33:AA:BB:CC",
		Alias:   "Bedroom",
	}
	if _, err := app.applyConfig(config); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/state", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	entries := response["entries"].(map[string]any)
	snapshots := response["state_snapshots"].(map[string]any)
	if _, ok := entries["bedroom"]; !ok {
		t.Fatalf("expected bedroom entry in state response")
	}
	if _, ok := snapshots["bedroom"]; !ok {
		t.Fatalf("expected bedroom state snapshot in state response")
	}
}

func TestEventsLimitReturnsMostRecentEvents(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	entry := atmotube.DeviceEntry{
		ConfigID: "bedroom",
		DeviceID: "bedroom",
		Address:  "11:22:33:AA:BB:CC",
	}
	app.appendLocalEvent("event.one", entry, nil)
	app.appendLocalEvent("event.two", entry, nil)
	app.appendLocalEvent("event.three", entry, nil)

	request := httptest.NewRequest(http.MethodGet, "/events?limit=2", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response struct {
		Events []map[string]any `json:"events"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(response.Events) != 2 {
		t.Fatalf("expected two events, got %d", len(response.Events))
	}
	if response.Events[0]["event_type"].(string) != "event.two" || response.Events[1]["event_type"].(string) != "event.three" {
		t.Fatalf("unexpected events payload: %#v", response.Events)
	}
}

func TestDeconfigureReturnsFalseForMissingConfig(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/deconfigure", bytes.NewReader([]byte(`{"config_id":"missing"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if response["removed"].(bool) {
		t.Fatalf("expected removed=false, got %#v", response["removed"])
	}
}

func TestConfigReturnsBadRequestForInvalidPayload(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/config", bytes.NewReader([]byte(`{"address":123}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func TestConfigSyncReturnsBadRequestForInvalidPayload(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/config/sync", bytes.NewReader([]byte(`{"configs":"not-an-array"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d: %s", recorder.Code, recorder.Body.String())
	}
}
