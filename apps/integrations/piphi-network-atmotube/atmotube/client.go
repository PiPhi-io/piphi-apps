package atmotube

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"tinygo.org/x/bluetooth"
)

type Client struct {
	adapter    *bluetooth.Adapter
	enableOnce sync.Once
	enableErr  error
	adapterMu  sync.Mutex
}

const preConnectScanTimeout = 4 * time.Second

func NewClient() *Client {
	return &Client{
		adapter: bluetooth.DefaultAdapter,
	}
}

func (c *Client) Enable() error {
	c.enableOnce.Do(func() {
		c.enableErr = c.adapter.Enable()
	})
	return c.enableErr
}

func (c *Client) Scan(ctx context.Context, timeout time.Duration, addressFilter string) ([]DiscoveredDevice, error) {
	var (
		devices []DiscoveredDevice
		err     error
	)
	c.withAdapterLock(func() {
		devices, err = c.scanUnlocked(ctx, timeout, addressFilter)
	})
	return devices, err
}

func (c *Client) scanUnlocked(ctx context.Context, timeout time.Duration, addressFilter string) ([]DiscoveredDevice, error) {
	if err := c.Enable(); err != nil {
		return nil, err
	}

	filter := strings.ToUpper(strings.TrimSpace(addressFilter))
	log.Printf("bluetooth_scan_started timeout=%s address_filter=%s", timeout, firstNonEmpty(filter, "<none>"))
	results := map[string]DiscoveredDevice{}
	var mu sync.Mutex

	stopTimer := time.AfterFunc(timeout, func() {
		_ = c.adapter.StopScan()
	})
	defer stopTimer.Stop()

	go func() {
		<-ctx.Done()
		_ = c.adapter.StopScan()
	}()

	err := c.adapter.Scan(func(adapter *bluetooth.Adapter, result bluetooth.ScanResult) {
		address := strings.ToUpper(result.Address.String())
		if filter != "" && address != filter {
			return
		}

		device := DiscoveredDevice{
			ID:                 address,
			DeviceID:           address,
			Address:            address,
			Name:               result.LocalName(),
			RSSI:               result.RSSI,
			HasAtmotubeService: result.HasServiceUUID(ServiceUUID),
		}

		for _, manufacturer := range result.ManufacturerData() {
			if manufacturer.CompanyID != 0xFFFF {
				continue
			}
			if parsed := parseAdvertisement(manufacturer.Data); parsed != nil {
				device.Broadcast = parsed
				break
			}
		}

		mu.Lock()
		results[address] = device
		mu.Unlock()

		if filter != "" && address == filter {
			_ = adapter.StopScan()
		}
	})
	if err != nil && !strings.Contains(strings.ToLower(err.Error()), "not scanning") {
		log.Printf("bluetooth_scan_failed address_filter=%s error=%v", firstNonEmpty(filter, "<none>"), err)
		return nil, err
	}

	mu.Lock()
	defer mu.Unlock()
	devices := make([]DiscoveredDevice, 0, len(results))
	for _, device := range results {
		devices = append(devices, device)
	}
	log.Printf("bluetooth_scan_completed address_filter=%s discovered=%d", firstNonEmpty(filter, "<none>"), len(devices))
	return devices, nil
}

func (c *Client) ReadSnapshot(address string) (Reading, error) {
	var (
		reading Reading
		err     error
	)
	c.withAdapterLock(func() {
		reading, err = c.readSnapshotLocked(address)
	})
	return reading, err
}

func (c *Client) readSnapshotLocked(address string) (Reading, error) {
	if err := c.Enable(); err != nil {
		return Reading{}, err
	}

	normalizedAddress := strings.ToUpper(strings.TrimSpace(address))
	if err := c.ensureDeviceVisibleLocked(normalizedAddress); err != nil {
		if isScanAlreadyInProgressError(err) {
			log.Printf("bluetooth_preconnect_scan_skipped address=%s reason=%v", normalizedAddress, err)
		} else {
			log.Printf("bluetooth_preconnect_scan_failed address=%s error=%v", normalizedAddress, err)
			return Reading{}, err
		}
	}
	log.Printf("bluetooth_connect_attempt address=%s", normalizedAddress)

	targetAddress, err := parseAddress(address)
	if err != nil {
		log.Printf("bluetooth_connect_address_parse_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, err
	}

	device, err := c.adapter.Connect(targetAddress, bluetooth.ConnectionParams{})
	if err != nil {
		log.Printf("bluetooth_connect_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("connect %s: %w", address, err)
	}
	log.Printf("bluetooth_connect_succeeded address=%s", normalizedAddress)
	defer func() {
		if err := device.Disconnect(); err != nil {
			log.Printf("bluetooth_disconnect_failed address=%s error=%v", normalizedAddress, err)
			return
		}
		log.Printf("bluetooth_disconnect_succeeded address=%s", normalizedAddress)
	}()

	services, err := device.DiscoverServices([]bluetooth.UUID{ServiceUUID})
	if err != nil {
		log.Printf("bluetooth_service_discovery_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("discover Atmotube service: %w", err)
	}
	if len(services) == 0 {
		log.Printf("bluetooth_service_missing address=%s service_uuid=%s", normalizedAddress, ServiceUUIDString)
		return Reading{}, fmt.Errorf("atmotube service not found on %s", address)
	}
	log.Printf("bluetooth_service_discovery_succeeded address=%s service_count=%d", normalizedAddress, len(services))

	characteristics, err := services[0].DiscoverCharacteristics([]bluetooth.UUID{
		VOCUUID,
		BMEUUID,
		StatusUUID,
		PMUUID,
	})
	if err != nil {
		log.Printf("bluetooth_characteristic_discovery_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("discover Atmotube characteristics: %w", err)
	}
	if len(characteristics) < 4 {
		log.Printf("bluetooth_characteristic_count_unexpected address=%s discovered=%d expected=4", normalizedAddress, len(characteristics))
		return Reading{}, fmt.Errorf("expected 4 Atmotube characteristics, got %d", len(characteristics))
	}
	log.Printf("bluetooth_characteristic_discovery_succeeded address=%s characteristic_count=%d", normalizedAddress, len(characteristics))

	vocPayload, err := readCharacteristic(characteristics[0], 4)
	if err != nil {
		log.Printf("bluetooth_voc_read_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("read VOC characteristic: %w", err)
	}
	bmePayload, err := readCharacteristic(characteristics[1], 8)
	if err != nil {
		log.Printf("bluetooth_bme_read_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("read BME characteristic: %w", err)
	}
	statusPayload, err := readCharacteristic(characteristics[2], 2)
	if err != nil {
		log.Printf("bluetooth_status_read_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("read status characteristic: %w", err)
	}
	pmPayload, err := readCharacteristic(characteristics[3], 12)
	if err != nil {
		log.Printf("bluetooth_pm_read_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, fmt.Errorf("read PM characteristic: %w", err)
	}

	vocPPB, err := parseVOC(vocPayload)
	if err != nil {
		log.Printf("bluetooth_voc_parse_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, err
	}
	humidity, temperatureC, pressureMbar, err := parseBME(bmePayload)
	if err != nil {
		log.Printf("bluetooth_bme_parse_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, err
	}
	infoByte, batteryPercent, err := parseStatus(statusPayload)
	if err != nil {
		log.Printf("bluetooth_status_parse_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, err
	}
	pm1, pm25, pm4, pm10, err := parsePM(pmPayload)
	if err != nil {
		log.Printf("bluetooth_pm_parse_failed address=%s error=%v", normalizedAddress, err)
		return Reading{}, err
	}

	reading := Reading{
		SampledAt:       time.Now().UTC().Format(time.RFC3339),
		VOCPPB:          vocPPB,
		VOCPPM:          float64(vocPPB) / 1000,
		HumidityPercent: humidity,
		TemperatureC:    temperatureC,
		PressureMbar:    pressureMbar,
		BatteryPercent:  batteryPercent,
		StatusByte:      statusPayload[0],
		InfoByte:        infoByte,
		PM1UGM3:         pm1,
		PM25UGM3:        pm25,
		PM4UGM3:         pm4,
		PM10UGM3:        pm10,
	}
	log.Printf(
		"bluetooth_snapshot_read_succeeded address=%s sampled_at=%s voc_ppb=%d temperature_c=%.2f humidity_percent=%.2f battery_percent=%d",
		normalizedAddress,
		reading.SampledAt,
		reading.VOCPPB,
		reading.TemperatureC,
		reading.HumidityPercent,
		reading.BatteryPercent,
	)
	return reading, nil
}

func (c *Client) ensureDeviceVisibleLocked(address string) error {
	ctx, cancel := context.WithTimeout(context.Background(), preConnectScanTimeout)
	defer cancel()

	log.Printf("bluetooth_preconnect_scan_started address=%s timeout=%s", address, preConnectScanTimeout)
	devices, err := c.scanUnlocked(ctx, preConnectScanTimeout, address)
	if err != nil {
		return fmt.Errorf("pre-connect scan %s: %w", address, err)
	}
	if len(devices) == 0 {
		return fmt.Errorf("device %s not found during pre-connect scan", address)
	}
	log.Printf("bluetooth_preconnect_scan_succeeded address=%s matches=%d", address, len(devices))
	return nil
}

func (c *Client) withAdapterLock(fn func()) {
	c.adapterMu.Lock()
	defer c.adapterMu.Unlock()
	fn()
}

func isScanAlreadyInProgressError(err error) bool {
	if err == nil {
		return false
	}
	message := strings.ToLower(err.Error())
	return strings.Contains(message, "already in progress")
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func parseAddress(value string) (bluetooth.Address, error) {
	mac, err := bluetooth.ParseMAC(strings.TrimSpace(value))
	if err != nil {
		return bluetooth.Address{}, fmt.Errorf("parse bluetooth address %q: %w", value, err)
	}
	return bluetooth.Address{
		MACAddress: bluetooth.MACAddress{
			MAC: mac,
		},
	}, nil
}

func readCharacteristic(characteristic bluetooth.DeviceCharacteristic, size int) ([]byte, error) {
	buffer := make([]byte, size)
	n, err := characteristic.Read(buffer)
	if err != nil {
		return nil, err
	}
	return buffer[:n], nil
}
