package atmotube

import (
	"encoding/json"
	"strings"
	"time"

	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"
)

const redactedValue = "[redacted]"

// SecretString is an in-memory secret value that never serializes or formats as
// plaintext. Bluetooth addresses identify a household device and are treated as
// private configuration even though they are not authentication credentials.
type SecretString string

func NewSecretString(value string) SecretString { return SecretString(strings.TrimSpace(value)) }
func (s SecretString) Reveal() string           { return string(s) }
func (s SecretString) String() string           { return redactedValue }
func (s SecretString) MarshalJSON() ([]byte, error) {
	return json.Marshal(redactedValue)
}
func (s *SecretString) UnmarshalJSON(data []byte) error {
	var value string
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	*s = NewSecretString(value)
	return nil
}

const (
	DefaultPollIntervalSeconds = 30
	ServiceUUIDString          = "DB450001-8E9A-4818-ADD7-6ED94A328AB4"
	VOCUUIDString              = "DB450002-8E9A-4818-ADD7-6ED94A328AB4"
	BMEUUIDString              = "DB450003-8E9A-4818-ADD7-6ED94A328AB4"
	StatusUUIDString           = "DB450004-8E9A-4818-ADD7-6ED94A328AB4"
	PMUUIDString               = "DB450005-8E9A-4818-ADD7-6ED94A328AB4"
)

type DeviceConfig struct {
	runtimekit.RuntimeConfig
	Address             SecretString `json:"address"`
	Alias               string       `json:"alias,omitempty"`
	PollIntervalSeconds int          `json:"poll_interval_seconds,omitempty"`
}

func (c DeviceConfig) Normalize() DeviceConfig {
	normalized := c
	normalized.Address = NewSecretString(strings.ToUpper(strings.TrimSpace(c.Address.Reveal())))
	normalized.Alias = strings.TrimSpace(c.Alias)
	if normalized.PollIntervalSeconds <= 0 {
		normalized.PollIntervalSeconds = DefaultPollIntervalSeconds
	}
	return normalized
}

func (c DeviceConfig) PollInterval() time.Duration {
	normalized := c.Normalize()
	return time.Duration(normalized.PollIntervalSeconds) * time.Second
}

func (c DeviceConfig) GetRuntimeConfigID() string {
	return c.Normalize().ID
}

type DiscoveredDevice struct {
	ID                 string         `json:"id"`
	DeviceID           string         `json:"device_id"`
	Address            string         `json:"address"`
	Name               string         `json:"name,omitempty"`
	RSSI               int16          `json:"rssi"`
	HasAtmotubeService bool           `json:"has_atmotube_service"`
	Broadcast          map[string]any `json:"broadcast,omitempty"`
}

type Reading struct {
	SampledAt       string  `json:"sampled_at"`
	VOCPPB          uint16  `json:"voc_ppb"`
	VOCPPM          float64 `json:"voc_ppm"`
	HumidityPercent float64 `json:"humidity_percent"`
	TemperatureC    float64 `json:"temperature_c"`
	PressureMbar    float64 `json:"pressure_mbar"`
	BatteryPercent  uint8   `json:"battery_percent"`
	StatusByte      uint8   `json:"status_byte"`
	InfoByte        uint8   `json:"info_byte"`
	PM1UGM3         float64 `json:"pm1_ugm3"`
	PM25UGM3        float64 `json:"pm25_ugm3"`
	PM4UGM3         float64 `json:"pm4_ugm3"`
	PM10UGM3        float64 `json:"pm10_ugm3"`
}

type DeviceEntry struct {
	ConfigID      string         `json:"config_id"`
	DeviceID      string         `json:"device_id"`
	ContainerID   string         `json:"container_id,omitempty"`
	IntegrationID string         `json:"integration_id,omitempty"`
	Address       SecretString   `json:"-"`
	Alias         string         `json:"alias,omitempty"`
	Config        DeviceConfig   `json:"config"`
	LatestState   Reading        `json:"latest_state,omitempty"`
	Metadata      map[string]any `json:"metadata,omitempty"`
}
