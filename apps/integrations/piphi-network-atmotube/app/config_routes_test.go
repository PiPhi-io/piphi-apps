package app

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

func TestConfigAppliesDeviceAndReturnsMetadata(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	body := []byte(`{"id":"bedroom","address":"11:22:33:aa:bb:cc","alias":"Bedroom","poll_interval_seconds":45}`)
	request := httptest.NewRequest(http.MethodPost, "/config", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Container-Id", "container-1")
	request.Header.Set("X-PiPhi-Integration-Token", "test-token")

	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if response["config_id"].(string) != "bedroom" {
		t.Fatalf("unexpected config_id: %#v", response["config_id"])
	}
	metadata := response["metadata"].(map[string]any)
	if metadata["address"].(string) != "11:22:33:AA:BB:CC" {
		t.Fatalf("expected normalized address, got %#v", metadata["address"])
	}
}

func TestConfigStoresLatestStateSnapshot(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/config", bytes.NewReader([]byte(`{"id":"bedroom","address":"11:22:33:AA:BB:CC"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if _, ok := app.registry.Get("bedroom"); !ok {
		t.Fatalf("expected registry entry after config apply")
	}
	if _, ok := app.registry.StateSnapshots()["bedroom"]; !ok {
		t.Fatalf("expected state snapshot after config apply")
	}
}

func TestConfigReturnsBadGatewayWhenReadSnapshotFails(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{readErr: errors.New("connect failed")}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/config", bytes.NewReader([]byte(`{"id":"bedroom","address":"11:22:33:AA:BB:CC"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("expected status 502, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func TestConfigNormalizesDefaultDeviceID(t *testing.T) {
	normalized := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom"},
		Address:       "11:22:33:aa:bb:cc",
	}.Normalize()

	if normalized.DeviceID != "bedroom" {
		t.Fatalf("expected normalized device_id=bedroom, got %q", normalized.DeviceID)
	}
}

func TestConfigNormalizesDefaultPollInterval(t *testing.T) {
	normalized := atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom"},
		Address:       "11:22:33:aa:bb:cc",
	}.Normalize()

	if normalized.PollIntervalSeconds != atmotube.DefaultPollIntervalSeconds {
		t.Fatalf("expected default poll interval %d, got %d", atmotube.DefaultPollIntervalSeconds, normalized.PollIntervalSeconds)
	}
}

func TestConfigSyncRemovesAllConfigsWhenSnapshotIsEmpty(t *testing.T) {
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

	request := httptest.NewRequest(http.MethodPost, "/config/sync", bytes.NewReader([]byte(`{"container_id":"container-1","configs":[]}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}
	if len(app.registry.IDs()) != 0 {
		t.Fatalf("expected registry to be empty after empty snapshot, got %#v", app.registry.IDs())
	}
}

func TestConfigsSyncAliasUsesSameHandler(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/configs/sync", bytes.NewReader([]byte(`{"container_id":"container-1","configs":[{"id":"bedroom","address":"11:22:33:AA:BB:CC"}]}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}
	if _, ok := app.registry.Get("bedroom"); !ok {
		t.Fatalf("expected registry entry after /configs/sync alias")
	}
}

func TestConfigSyncReturnsBadGatewayWhenApplyFails(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{readErr: errors.New("connect failed")}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/config/sync", bytes.NewReader([]byte(`{"container_id":"container-1","configs":[{"id":"bedroom","address":"11:22:33:AA:BB:CC"}]}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("expected status 502, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func TestDeconfigureRemovesExistingConfig(t *testing.T) {
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

	request := httptest.NewRequest(http.MethodPost, "/deconfigure", bytes.NewReader([]byte(`{"config_id":"bedroom"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", recorder.Code, recorder.Body.String())
	}
	if _, ok := app.registry.Get("bedroom"); ok {
		t.Fatalf("expected bedroom to be removed from registry")
	}
}

func TestDeconfigureReturnsRemainingConfigCount(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	router := app.Router()

	first := atmotube.DeviceConfig{RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom", DeviceID: "bedroom"}, Address: "11:22:33:AA:BB:CC"}
	second := atmotube.DeviceConfig{RuntimeConfig: runtimekit.RuntimeConfig{ID: "office", DeviceID: "office"}, Address: "22:33:44:BB:CC:DD"}
	if _, err := app.applyConfig(first); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}
	if _, err := app.applyConfig(second); err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}

	request := httptest.NewRequest(http.MethodPost, "/deconfigure", bytes.NewReader([]byte(`{"config_id":"bedroom"}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	metadata := response["metadata"].(map[string]any)
	if metadata["remaining_configs"].(float64) != 1 {
		t.Fatalf("expected remaining_configs=1, got %#v", metadata["remaining_configs"])
	}
}

func TestApplyConfigUsesFallbackIntegrationID(t *testing.T) {
	app := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)

	entry, err := app.applyConfig(atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID:          "bedroom",
			DeviceID:    "bedroom",
			ContainerID: "container-1",
		},
		Address: "11:22:33:AA:BB:CC",
	})
	if err != nil {
		t.Fatalf("applyConfig failed: %v", err)
	}
	if entry.IntegrationID != integrationID {
		t.Fatalf("expected fallback integration id %q, got %q", integrationID, entry.IntegrationID)
	}
}
