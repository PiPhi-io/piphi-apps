package atmotube

import (
	"context"
	"errors"
	"strings"
	"sync"
	"time"
)

const FakeAddress = "02:00:00:00:00:01"

// FakeClient is a deterministic, hardware-free BLE transport for CI and local
// contract testing. It is enabled only through the explicit simulation flag.
type FakeClient struct {
	mu        sync.Mutex
	clock     func() time.Time
	readCount int
	failReads int
}

func NewFakeClient(clock func() time.Time) *FakeClient {
	if clock == nil {
		clock = func() time.Time { return time.Unix(1_700_000_000, 0).UTC() }
	}
	return &FakeClient{clock: clock}
}

func (f *FakeClient) FailNextReads(count int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.failReads = count
}

func (f *FakeClient) Scan(_ context.Context, _ time.Duration, addressFilter string) ([]DiscoveredDevice, error) {
	if filter := strings.ToUpper(strings.TrimSpace(addressFilter)); filter != "" && filter != FakeAddress {
		return []DiscoveredDevice{}, nil
	}
	return []DiscoveredDevice{{
		ID:                 FakeAddress,
		DeviceID:           FakeAddress,
		Address:            FakeAddress,
		Name:               "Atmotube Pro (simulation)",
		RSSI:               -42,
		HasAtmotubeService: true,
		Broadcast:          map[string]any{"voc_ppb": 120},
	}}, nil
}

func (f *FakeClient) ReadSnapshot(address string) (Reading, error) {
	if strings.ToUpper(strings.TrimSpace(address)) != FakeAddress {
		return Reading{}, errors.New("simulated device not found")
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.failReads > 0 {
		f.failReads--
		return Reading{}, errors.New("simulated transient BLE read failure")
	}
	f.readCount++
	step := float64(f.readCount - 1)
	return Reading{
		SampledAt:       f.clock().Add(time.Duration(f.readCount-1) * time.Second).Format(time.RFC3339),
		VOCPPB:          uint16(120 + f.readCount - 1),
		VOCPPM:          float64(120+f.readCount-1) / 1000,
		HumidityPercent: 45 + step/10,
		TemperatureC:    22 + step/10,
		PressureMbar:    1013.2,
		BatteryPercent:  87,
		StatusByte:      1,
		InfoByte:        2,
		PM1UGM3:         1.1,
		PM25UGM3:        2.3 + step/10,
		PM4UGM3:         3.4,
		PM10UGM3:        4.5,
	}, nil
}
