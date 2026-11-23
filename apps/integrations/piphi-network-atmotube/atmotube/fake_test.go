package atmotube

import (
	"context"
	"testing"
	"time"
)

func TestFakeClientIsDeterministicAndFailureScriptIsBounded(t *testing.T) {
	clock := func() time.Time { return time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC) }
	first := NewFakeClient(clock)
	second := NewFakeClient(clock)
	devices, err := first.Scan(context.Background(), time.Second, "")
	if err != nil || len(devices) != 1 || devices[0].Address != FakeAddress {
		t.Fatalf("unexpected deterministic discovery: %#v, %v", devices, err)
	}
	one, err := first.ReadSnapshot(FakeAddress)
	if err != nil {
		t.Fatal(err)
	}
	two, err := second.ReadSnapshot(FakeAddress)
	if err != nil {
		t.Fatal(err)
	}
	if one != two {
		t.Fatalf("fresh fake clients differ: %#v != %#v", one, two)
	}
	first.FailNextReads(1)
	if _, err := first.ReadSnapshot(FakeAddress); err == nil {
		t.Fatal("expected scripted failure")
	}
	if _, err := first.ReadSnapshot(FakeAddress); err != nil {
		t.Fatalf("scripted failure did not recover: %v", err)
	}
}
