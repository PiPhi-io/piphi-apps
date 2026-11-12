package app

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

func TestDiscoverGetUsesDefaultTimeout(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}
	if fakeBLE.scanCalls != 1 {
		t.Fatalf("expected one scan call, got %d", fakeBLE.scanCalls)
	}
	if fakeBLE.lastTimeout != 6*time.Second {
		t.Fatalf("expected default 6s timeout, got %s", fakeBLE.lastTimeout)
	}
}

func TestDiscoverPostUsesCustomScanSeconds(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/discover", bytes.NewReader([]byte(`{"inputs":{"scan_seconds":12}}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}
	if fakeBLE.lastTimeout != 12*time.Second {
		t.Fatalf("expected custom 12s timeout, got %s", fakeBLE.lastTimeout)
	}
}

func TestDiscoverPostPassesAddressFilterToBLEClient(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/discover", bytes.NewReader([]byte(`{"inputs":{"address":"11:22:33:AA:BB:CC"}}`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}
	if fakeBLE.lastFilter != "11:22:33:AA:BB:CC" {
		t.Fatalf("expected address filter to be forwarded, got %q", fakeBLE.lastFilter)
	}
}

func TestDiscoverPostIgnoresInvalidJSONAndStillScans(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodPost, "/discover", bytes.NewReader([]byte(`{"inputs":`)))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}
	if fakeBLE.scanCalls != 1 {
		t.Fatalf("expected scan to still run, got %d calls", fakeBLE.scanCalls)
	}
}

func TestDiscoverReturnsBadGatewayOnBLEScanError(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{scanErr: errors.New("scan failed")}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("expected status 502, got %d: %s", recorder.Code, recorder.Body.String())
	}
}

func TestDiscoverResponseIncludesBroadcastMetadata(t *testing.T) {
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
				Broadcast: map[string]any{
					"voc_ppb": 220,
				},
			},
		},
	}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if response.Devices[0].Broadcast["voc_ppb"].(float64) != 220 {
		t.Fatalf("expected broadcast voc_ppb=220, got %#v", response.Devices[0].Broadcast["voc_ppb"])
	}
}

func TestDiscoverReturnsEmptyDeviceListWhenScannerFindsNothing(t *testing.T) {
	gin.SetMode(gin.TestMode)

	app := NewWithOptions(&fakeBLEClient{discovered: nil}, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(response.Devices) != 0 {
		t.Fatalf("expected empty device list, got %d devices", len(response.Devices))
	}
}

func TestDiscoverFiltersCaseInsensitiveAtmotubeName(t *testing.T) {
	gin.SetMode(gin.TestMode)

	fakeBLE := &fakeBLEClient{
		discovered: []atmotube.DiscoveredDevice{
			{
				ID:                 "11:22:33:AA:BB:CC",
				DeviceID:           "11:22:33:AA:BB:CC",
				Address:            "11:22:33:AA:BB:CC",
				Name:               "atmotube mini",
				RSSI:               -48,
				HasAtmotubeService: false,
			},
		},
	}
	app := NewWithOptions(fakeBLE, false)
	router := app.Router()

	request := httptest.NewRequest(http.MethodGet, "/discover", nil)
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, request)

	var response struct {
		Devices []atmotube.DiscoveredDevice `json:"devices"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if len(response.Devices) != 1 {
		t.Fatalf("expected one case-insensitive name match, got %d", len(response.Devices))
	}
}
