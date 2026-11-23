package app

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

func TestOnlyHealthIsPublicAndRuntimeAuthFailsClosed(t *testing.T) {
	application, err := NewWithSettings(&fakeBLEClient{}, Options{IdentityKey: []byte("0123456789abcdef0123456789abcdef")})
	if err != nil {
		t.Fatal(err)
	}
	router := application.Router()

	health := httptest.NewRecorder()
	router.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/health", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("health must remain public, got %d", health.Code)
	}
	for _, path := range []string{"/diagnostics", "/ui", "/discover", "/entities", "/state", "/events"} {
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		if response.Code != http.StatusServiceUnavailable {
			t.Fatalf("%s must fail closed without configured auth, got %d", path, response.Code)
		}
	}

	secured, err := NewWithSettings(&fakeBLEClient{}, Options{ExpectedToken: "expected", IdentityKey: []byte("0123456789abcdef0123456789abcdef")})
	if err != nil {
		t.Fatal(err)
	}
	wrong := httptest.NewRequest(http.MethodGet, "/entities", nil)
	wrong.Header.Set(runtimeTokenHeader, "wrong")
	response := httptest.NewRecorder()
	secured.Router().ServeHTTP(response, wrong)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("wrong token must be rejected, got %d", response.Code)
	}
}

func TestRecursiveRedactionRemovesNestedSecretsAndAddresses(t *testing.T) {
	redacted := redactRecursive(map[string]any{
		"nested": []any{map[string]any{"api_token": "canary-secret", "message": "device 11:22:33:AA:BB:CC failed"}},
	})
	encoded, err := json.Marshal(redacted)
	if err != nil {
		t.Fatal(err)
	}
	text := string(encoded)
	for _, forbidden := range []string{"canary-secret", "11:22:33:AA:BB:CC"} {
		if strings.Contains(text, forbidden) {
			t.Fatalf("redacted payload contains %q: %s", forbidden, text)
		}
	}
}

func TestFailedReconfigurationPreservesPreviousConfig(t *testing.T) {
	transport := &fakeBLEClient{reading: sampleReading()}
	application := NewWithOptions(transport, false)
	before, err := application.applyConfig(atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom"}, Address: "11:22:33:AA:BB:CC", Alias: "working",
	})
	if err != nil {
		t.Fatal(err)
	}
	transport.readErr = errors.New("replacement unavailable at 22:33:44:BB:CC:DD")
	_, err = application.applyConfig(atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{ID: "bedroom"}, Address: "22:33:44:BB:CC:DD", Alias: "replacement",
	})
	if err == nil {
		t.Fatal("expected replacement to fail")
	}
	after, ok := application.registry.Get("bedroom")
	if !ok || after.Alias != before.Alias || after.Address.Reveal() != before.Address.Reveal() {
		t.Fatalf("failed replacement changed active config: %#v", after)
	}
}

func TestPersistedConfigRestoresOpaqueIdentityAfterRestart(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "state.json")
	key := []byte("0123456789abcdef0123456789abcdef")
	first, err := NewWithSettings(&fakeBLEClient{reading: sampleReading()}, Options{
		StatePath: statePath, ExpectedToken: "test-token", IdentityKey: key,
	})
	if err != nil {
		t.Fatal(err)
	}
	entry, err := first.applyConfig(atmotube.DeviceConfig{Address: "11:22:33:AA:BB:CC", Alias: "Bedroom"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(entry.DeviceID, "11:22") || !strings.HasPrefix(entry.DeviceID, "atm_") {
		t.Fatalf("device identity is not opaque: %q", entry.DeviceID)
	}
	info, err := os.Stat(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("state file permissions = %o, want 600", info.Mode().Perm())
	}

	second, err := NewWithSettings(&fakeBLEClient{reading: sampleReading()}, Options{StatePath: statePath, ExpectedToken: "test-token"})
	if err != nil {
		t.Fatal(err)
	}
	restored, ok := second.registry.Get(entry.ConfigID)
	if !ok || restored.DeviceID != entry.DeviceID {
		t.Fatalf("restart did not restore stable identity: %#v", restored)
	}
	encoded, err := json.Marshal(restored)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(encoded, []byte("11:22:33:AA:BB:CC")) {
		t.Fatalf("runtime state exposed private address: %s", encoded)
	}
}

func TestStaleAndRecoveryTransitionsAreBounded(t *testing.T) {
	transport := &fakeBLEClient{readErr: errors.New("device 11:22:33:AA:BB:CC offline")}
	application := NewWithOptions(transport, false)
	entry := atmotube.DeviceEntry{
		ConfigID: "bedroom", DeviceID: "atm_test", Address: "11:22:33:AA:BB:CC",
		Config: atmotube.DeviceConfig{Address: "11:22:33:AA:BB:CC", PollIntervalSeconds: 5},
	}
	application.registry.Set(entry.ConfigID, entry)
	application.pollOnce(entry)
	application.pollOnce(entry)
	application.pollOnce(entry)
	transport.readErr = nil
	transport.reading = sampleReading()
	application.pollOnce(entry)

	events := application.registry.RecentEvents()
	var stale, recovered int
	for _, event := range events {
		switch event["event_type"] {
		case "atmotube.connection.stale":
			stale++
		case "atmotube.connection.recovered":
			recovered++
		}
		encoded, _ := json.Marshal(event)
		if bytes.Contains(encoded, []byte("11:22:33:AA:BB:CC")) {
			t.Fatalf("event leaked private address: %s", encoded)
		}
	}
	if stale != 1 || recovered != 1 {
		t.Fatalf("expected one stale and one recovery transition, got stale=%d recovered=%d", stale, recovered)
	}
}

func TestLatePollCannotResurrectRemovedConfig(t *testing.T) {
	application := NewWithOptions(&fakeBLEClient{reading: sampleReading()}, false)
	entry := atmotube.DeviceEntry{
		ConfigID: "removed", DeviceID: "atm_removed", Address: "11:22:33:AA:BB:CC",
		Config: atmotube.DeviceConfig{Address: "11:22:33:AA:BB:CC", PollIntervalSeconds: 5},
	}
	application.pollOnce(entry)
	if _, exists := application.registry.Get("removed"); exists {
		t.Fatal("late poll resurrected a config that was no longer registered")
	}
}
