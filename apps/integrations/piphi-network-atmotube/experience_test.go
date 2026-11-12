package main

import (
	"encoding/json"
	"os"
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
