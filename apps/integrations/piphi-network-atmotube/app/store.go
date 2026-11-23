package app

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

type persistedConfig struct {
	ID                  string `json:"id"`
	DeviceID            string `json:"device_id"`
	ContainerID         string `json:"container_id,omitempty"`
	IntegrationID       string `json:"integration_id,omitempty"`
	Address             string `json:"address"`
	Alias               string `json:"alias,omitempty"`
	PollIntervalSeconds int    `json:"poll_interval_seconds"`
}

type persistedState struct {
	SchemaVersion int               `json:"schema_version"`
	IdentityKey   string            `json:"identity_key"`
	Configs       []persistedConfig `json:"configs"`
}

type StateStore interface {
	Load() (persistedState, error)
	Save(persistedState) error
}

type fileStateStore struct{ path string }

func newFileStateStore(path string) StateStore {
	if path == "" {
		return nil
	}
	return &fileStateStore{path: path}
}

func (s *fileStateStore) Load() (persistedState, error) {
	data, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		return persistedState{}, nil
	}
	if err != nil {
		return persistedState{}, fmt.Errorf("read persisted runtime state: %w", err)
	}
	var state persistedState
	if err := json.Unmarshal(data, &state); err != nil {
		return persistedState{}, fmt.Errorf("decode persisted runtime state: %w", err)
	}
	if state.SchemaVersion != 1 {
		return persistedState{}, fmt.Errorf("unsupported persisted runtime state schema %d", state.SchemaVersion)
	}
	return state, nil
}

func (s *fileStateStore) Save(state persistedState) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return fmt.Errorf("create runtime state directory: %w", err)
	}
	data, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("encode runtime state: %w", err)
	}
	temporary, err := os.CreateTemp(filepath.Dir(s.path), ".atmotube-state-*")
	if err != nil {
		return fmt.Errorf("create temporary runtime state: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		_ = temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		_ = temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		_ = temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, s.path); err != nil {
		return fmt.Errorf("commit runtime state: %w", err)
	}
	directory, err := os.Open(filepath.Dir(s.path))
	if err != nil {
		return fmt.Errorf("open runtime state directory: %w", err)
	}
	defer directory.Close()
	if err := directory.Sync(); err != nil {
		return fmt.Errorf("sync runtime state directory: %w", err)
	}
	return nil
}

func generateIdentityKey() ([]byte, error) {
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, fmt.Errorf("generate identity key: %w", err)
	}
	return key, nil
}

func configFromPersisted(value persistedConfig) atmotube.DeviceConfig {
	return atmotube.DeviceConfig{
		RuntimeConfig: runtimekit.RuntimeConfig{
			ID: value.ID, DeviceID: value.DeviceID, ContainerID: value.ContainerID, IntegrationID: value.IntegrationID,
		},
		Address: atmotube.NewSecretString(value.Address), Alias: value.Alias, PollIntervalSeconds: value.PollIntervalSeconds,
	}
}

func persistedFromConfig(value atmotube.DeviceConfig) persistedConfig {
	return persistedConfig{
		ID: value.ID, DeviceID: value.DeviceID, ContainerID: value.ContainerID, IntegrationID: value.IntegrationID,
		Address: value.Address.Reveal(), Alias: value.Alias, PollIntervalSeconds: value.PollIntervalSeconds,
	}
}

func encodeIdentityKey(key []byte) string { return base64.RawStdEncoding.EncodeToString(key) }
func decodeIdentityKey(value string) ([]byte, error) {
	key, err := base64.RawStdEncoding.DecodeString(value)
	if err != nil || len(key) != 32 {
		return nil, errors.New("persisted identity key is invalid")
	}
	return key, nil
}
