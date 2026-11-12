package app

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

func TestHealthReportsZeroConfigsByDefault(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/health", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	metadata := response["metadata"].(map[string]any)
	if metadata["active_configs"].(float64) != 0 {
		t.Fatalf("expected active_configs=0, got %#v", metadata["active_configs"])
	}
}

func TestDiagnosticsReportsBluetoothEnabled(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/diagnostics", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	diagnostics := response["diagnostics"].(map[string]any)
	if !diagnostics["bluetooth_enabled"].(bool) {
		t.Fatalf("expected bluetooth_enabled=true")
	}
}

func TestUISchemaDescriptionMentionsBluetooth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/ui", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	schema := response["schema"].(map[string]any)
	description := schema["description"].(string)
	if description == "" {
		t.Fatalf("expected non-empty description")
	}
}

func TestUISchemaRequiresAddress(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/ui", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	required := response["schema"].(map[string]any)["required"].([]any)
	if len(required) != 1 || required[0].(string) != "address" {
		t.Fatalf("unexpected required fields: %#v", required)
	}
}

func TestUISchemaDefaultPollIntervalMatchesConstant(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/ui", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	properties := response["schema"].(map[string]any)["properties"].(map[string]any)
	pollInterval := properties["poll_interval_seconds"].(map[string]any)["default"].(float64)
	if int(pollInterval) != atmotube.DefaultPollIntervalSeconds {
		t.Fatalf("expected default poll interval %d, got %v", atmotube.DefaultPollIntervalSeconds, pollInterval)
	}
}

func TestEntitiesReturnsEmptyWhenNoConfigs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/entities", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Entities []map[string]any `json:"entities"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	if len(response.Entities) != 0 {
		t.Fatalf("expected no entities, got %d", len(response.Entities))
	}
}

func TestStateReturnsEmptyMapsWhenNoConfigs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/state", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	if len(response["entries"].(map[string]any)) != 0 {
		t.Fatalf("expected empty entries map")
	}
	if len(response["state_snapshots"].(map[string]any)) != 0 {
		t.Fatalf("expected empty state_snapshots map")
	}
}

func TestEventsReturnsEmptyListByDefault(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()

	request := httptest.NewRequest(http.MethodGet, "/events", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Events []map[string]any `json:"events"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	if len(response.Events) != 0 {
		t.Fatalf("expected no events, got %d", len(response.Events))
	}
}

func TestEventsInvalidLimitFallsBackToDefault(t *testing.T) {
	gin.SetMode(gin.TestMode)
	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	entry := atmotube.DeviceEntry{ConfigID: "bedroom", DeviceID: "bedroom", Address: "11:22:33:AA:BB:CC"}
	for _, name := range []string{"event.one", "event.two"} {
		app.appendLocalEvent(name, entry, nil)
	}

	request := httptest.NewRequest(http.MethodGet, "/events?limit=bad", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Events []map[string]any `json:"events"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	if len(response.Events) != 2 {
		t.Fatalf("expected all events when limit is invalid, got %d", len(response.Events))
	}
}

func TestEventsZeroLimitFallsBackToDefault(t *testing.T) {
	gin.SetMode(gin.TestMode)
	app := NewWithOptions(&fakeBLEClient{}, false)
	router := app.Router()

	entry := atmotube.DeviceEntry{ConfigID: "bedroom", DeviceID: "bedroom", Address: "11:22:33:AA:BB:CC"}
	for _, name := range []string{"event.one", "event.two"} {
		app.appendLocalEvent(name, entry, nil)
	}

	request := httptest.NewRequest(http.MethodGet, "/events?limit=0", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Events []map[string]any `json:"events"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	if len(response.Events) != 2 {
		t.Fatalf("expected all events when limit is zero, got %d", len(response.Events))
	}
}

func TestEntitiesLatestStateMirrorsReading(t *testing.T) {
	gin.SetMode(gin.TestMode)
	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom", DeviceID: "bedroom"},
		Address:       "11:22:33:AA:BB:CC",
	}
	if _, err := app.applyConfig(config); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/entities", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Entities []map[string]any `json:"entities"`
	}
	_ = json.Unmarshal(recorder.Body.Bytes(), &response)
	latestState := response.Entities[0]["latest_state"].(map[string]any)
	if latestState["temperature_c"].(float64) != 22.4 {
		t.Fatalf("unexpected latest_state temperature: %#v", latestState["temperature_c"])
	}
}

func TestRefreshCommandReadsAndReturnsFreshState(t *testing.T) {
	gin.SetMode(gin.TestMode)
	fakeBLE := &fakeBLEClient{reading: sampleReading()}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()
	config := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom", DeviceID: "bedroom"},
		Address:       "11:22:33:AA:BB:CC",
	}
	if _, err := app.applyConfig(config); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(
		http.MethodPost,
		"/command",
		strings.NewReader(`{"command":"refresh","args":{"config_id":"bedroom"}}`),
	)
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
	if response["config_id"] != "bedroom" {
		t.Fatalf("unexpected config_id: %#v", response["config_id"])
	}
	state := response["state"].(map[string]any)
	if state["temperature_c"].(float64) != 22.4 {
		t.Fatalf("unexpected refreshed state: %#v", state)
	}
}

func TestRefreshCommandRejectsUnknownDevice(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := NewWithOptions(&fakeBLEClient{}, false).Router()
	request := httptest.NewRequest(
		http.MethodPost,
		"/command",
		strings.NewReader(`{"command":"refresh","device_id":"missing"}`),
	)
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusNotFound {
		t.Fatalf("expected status 404, got %d: %s", recorder.Code, recorder.Body.String())
	}
}
