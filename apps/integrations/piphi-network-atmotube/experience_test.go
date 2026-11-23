package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func readJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	if err := json.Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

func TestReleaseAndCapabilityContractsStaySynchronized(t *testing.T) {
	manifest := readJSON(t, "src/manifest.json")
	appMetadata := readJSON(t, "piphi-app.json")
	packages := array(t, appMetadata["packages"])
	if len(packages) != 1 || object(t, packages[0])["version"] != manifest["version"] {
		t.Fatal("manifest and release metadata versions differ")
	}
	if object(t, object(t, packages[0])["artifact"])["kind"] != "oci" || appMetadata["ci"].(map[string]any)["enforcement"] != "full" {
		t.Fatal("Atmotube must use the full OCI release path")
	}

	catalog := readJSON(t, "capability-catalog.json")
	manifestCapabilities := object(t, manifest["capabilities"])
	behaviors := readJSON(t, "src/behaviors.json")
	mapped := map[string]bool{}
	for _, raw := range array(t, object(t, behaviors["telemetry"])["capabilityMappings"]) {
		mapped[object(t, raw)["nativeMetric"].(string)] = true
	}
	seen := map[string]bool{}
	for _, raw := range array(t, catalog["capabilities"]) {
		capability := object(t, raw)
		id := capability["id"].(string)
		if seen[id] {
			t.Fatalf("duplicate catalog capability %s", id)
		}
		seen[id] = true
		if capability["status"] != "implemented" {
			if _, advertised := manifestCapabilities[id]; advertised {
				t.Fatalf("excluded capability %s is advertised", id)
			}
			continue
		}
		if capability["kind"] == "telemetry" {
			if _, advertised := manifestCapabilities[id]; !advertised || !mapped[id] {
				t.Fatalf("implemented telemetry %s is not synchronized", id)
			}
		}
	}

	dockerfile, err := os.ReadFile("Dockerfile")
	if err != nil {
		t.Fatal(err)
	}
	dockerText := string(dockerfile)
	for _, required := range []string{"@sha256:", "USER 65532:65532", "CGO_ENABLED=0", "-mod=readonly"} {
		if !strings.Contains(dockerText, required) {
			t.Fatalf("Dockerfile missing reproducibility/security contract %q", required)
		}
	}
}

func TestLinuxBlueZDeploymentContract(t *testing.T) {
	readme, err := os.ReadFile("README.md")
	if err != nil {
		t.Fatal(err)
	}
	readmeText := string(readme)
	for _, required := range []string{
		"dst=/var/run/dbus/system_bus_socket,readonly",
		"--security-opt apparmor=piphi-atmotube-ble",
		"--user \"$PIPHI_ATMOTUBE_UID:$PIPHI_ATMOTUBE_GID\"",
		"/etc/apparmor.d/piphi-atmotube-ble",
		"apparmor_parser -r -W /etc/apparmor.d/piphi-atmotube-ble",
	} {
		if !strings.Contains(readmeText, required) {
			t.Fatalf("README missing qualified BlueZ deployment contract %q", required)
		}
	}
	if strings.Contains(readmeText, "dst=/run/dbus/system_bus_socket,readonly") {
		t.Fatal("README uses the wrong TinyGo D-Bus socket destination")
	}

	profile, err := os.ReadFile("deploy/apparmor/piphi-atmotube-ble")
	if err != nil {
		t.Fatal(err)
	}
	profileText := string(profile)
	for _, required := range []string{
		"profile piphi-atmotube-ble",
		"member={Hello,AddMatch,RemoveMatch,GetNameOwner,NameHasOwner}",
		"peer=(name=org.bluez)",
	} {
		if !strings.Contains(profileText, required) {
			t.Fatalf("AppArmor profile missing BlueZ contract %q", required)
		}
	}
}

func object(t *testing.T, value any) map[string]any {
	t.Helper()
	result, ok := value.(map[string]any)
	if !ok {
		t.Fatalf("expected object, got %T", value)
	}
	return result
}

func array(t *testing.T, value any) []any {
	t.Helper()
	result, ok := value.([]any)
	if !ok {
		t.Fatalf("expected array, got %T", value)
	}
	return result
}

func TestAirQualityExperienceMatchesManifest(t *testing.T) {
	manifest := readJSON(t, "src/manifest.json")
	packageSource := readJSON(t, "experiences/air-quality/package.source.json")
	identity := object(t, packageSource["identity"])
	if packageSource["owning_integration_id"] != manifest["id"] || identity["version"] != manifest["version"] {
		t.Fatal("experience owner or version differs from integration manifest")
	}
	registryID := identity["publisher_id"].(string) + "." + identity["package_id"].(string)
	ui := object(t, manifest["ui"])
	references := array(t, ui["experience_packages"])
	if len(references) != 1 || object(t, references[0])["registry_id"] != registryID || object(t, references[0])["auto_install"] != true {
		t.Fatal("manifest must auto-install the local experience package")
	}
	widgets := array(t, packageSource["widgets"])
	if len(widgets) != 1 {
		t.Fatal("expected one focused air-quality widget")
	}
	widget := object(t, widgets[0])
	if widget["runtime"] != "declarative" {
		t.Fatal("air-quality widget must use Core's declarative runtime")
	}
	certification := object(t, widget["certification"])
	verified := array(t, certification["verified_gates"])
	evidence := object(t, certification["evidence"])
	if len(verified) != 9 || len(evidence) != len(verified) {
		t.Fatal("air-quality widget must carry complete declarative certification evidence")
	}
	for _, gateValue := range verified {
		gate := gateValue.(string)
		if _, ok := evidence[gate]; !ok {
			t.Fatalf("certification evidence missing %s", gate)
		}
	}
	capabilities := object(t, manifest["capabilities"])
	slots := map[string]bool{}
	for _, value := range array(t, widget["binding_slots"]) {
		slot := object(t, value)
		id := slot["id"].(string)
		if slots[id] {
			t.Fatalf("duplicate binding slot %s", id)
		}
		slots[id] = true
		for _, requirement := range array(t, slot["capability_requirements"]) {
			capability := requirement.(string)
			if _, ok := capabilities[capability]; !ok {
				t.Fatalf("slot %s requests undeclared capability %s", id, capability)
			}
		}
	}
	recipe := object(t, widget["recipe"])
	for _, value := range array(t, recipe["items"]) {
		item := object(t, value)
		if !slots[item["slot_id"].(string)] {
			t.Fatalf("recipe references undeclared slot %v", item["slot_id"])
		}
	}
	for _, value := range array(t, widget["interaction_targets"]) {
		target := object(t, value)
		if target["kind"] == "binding" && !slots[target["binding_slot_id"].(string)] {
			t.Fatalf("interaction references undeclared slot %v", target["binding_slot_id"])
		}
	}
}
