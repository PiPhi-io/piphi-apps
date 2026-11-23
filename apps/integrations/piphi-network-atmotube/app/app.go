package app

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"
	"github.com/PiPhi-io/piphi-runtime-kit-go/adapters"
	"github.com/gin-gonic/gin"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

const integrationID = "piphi-network-atmotube-pro"
const version = "0.1.7"

type runtimeStatus struct {
	LastSuccess         time.Time
	ConsecutiveFailures int
	Stale               bool
	LastError           string
}

type Options struct {
	EnablePolling bool
	StatePath     string
	ExpectedToken string
	IdentityKey   []byte
}

type App struct {
	runtime       *runtimekit.RuntimeContext
	registry      *runtimekit.RuntimeRegistry[atmotube.DeviceEntry, atmotube.Reading, map[string]any]
	state         *runtimekit.RuntimeStateService[atmotube.DeviceEntry, atmotube.Reading, map[string]any]
	telemetry     *runtimekit.TelemetryClient
	ble           BLEClient
	enablePolling bool
	store         StateStore
	identityKey   []byte
	expectedToken string
	restoreError  string

	mu       sync.Mutex
	configMu sync.Mutex
	pollers  map[string]context.CancelFunc
	status   map[string]runtimeStatus
}

type BLEClient interface {
	Scan(ctx context.Context, timeout time.Duration, addressFilter string) ([]atmotube.DiscoveredDevice, error)
	ReadSnapshot(address string) (atmotube.Reading, error)
}

func New() *App {
	var ble BLEClient = atmotube.NewClient()
	if strings.EqualFold(strings.TrimSpace(os.Getenv("PIPHI_ATMOTUBE_SIMULATION")), "true") || os.Getenv("PIPHI_ATMOTUBE_SIMULATION") == "1" {
		ble = atmotube.NewFakeClient(nil)
	}
	statePath := strings.TrimSpace(os.Getenv("PIPHI_ATMOTUBE_STATE_PATH"))
	if statePath == "" {
		statePath = "/var/lib/piphi-atmotube/state.json"
	}
	application, err := NewWithSettings(ble, Options{
		EnablePolling: true,
		StatePath:     statePath,
		ExpectedToken: strings.TrimSpace(os.Getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")),
	})
	if err != nil {
		log.Printf("runtime_restore_failed error=%s", publicError(err))
	}
	return application
}

func NewWithOptions(ble BLEClient, enablePolling bool) *App {
	application, _ := NewWithSettings(ble, Options{
		EnablePolling: enablePolling,
		ExpectedToken: strings.TrimSpace(os.Getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")),
		IdentityKey:   []byte("0123456789abcdef0123456789abcdef"),
	})
	return application
}

func NewWithSettings(ble BLEClient, options Options) (*App, error) {
	runtime := runtimekit.NewRuntimeContext()
	registry := runtimekit.NewRuntimeRegistry[atmotube.DeviceEntry, atmotube.Reading, map[string]any](100)
	store := newFileStateStore(options.StatePath)
	identityKey := append([]byte(nil), options.IdentityKey...)
	var restored persistedState
	var restoreErr error
	if store != nil {
		restored, restoreErr = store.Load()
		if restoreErr == nil && restored.IdentityKey != "" {
			identityKey, restoreErr = decodeIdentityKey(restored.IdentityKey)
		}
	}
	if len(identityKey) == 0 && restoreErr == nil {
		identityKey, restoreErr = generateIdentityKey()
	}
	application := &App{
		runtime:       runtime,
		registry:      registry,
		state:         runtimekit.NewRuntimeStateService(registry),
		telemetry:     runtimekit.NewTelemetryClient(runtime.ProcessState, "", 0),
		ble:           ble,
		enablePolling: options.EnablePolling,
		store:         store,
		identityKey:   identityKey,
		expectedToken: strings.TrimSpace(options.ExpectedToken),
		pollers:       map[string]context.CancelFunc{},
		status:        map[string]runtimeStatus{},
	}
	if restoreErr != nil {
		application.restoreError = publicError(restoreErr)
	}
	if err := application.state.Provide(application.refreshAllState, integrationID); err != nil {
		panic(err)
	}
	if restoreErr == nil {
		for _, persisted := range restored.Configs {
			config, err := application.normalizeConfig(configFromPersisted(persisted))
			if err != nil {
				restoreErr = err
				application.restoreError = publicError(err)
				break
			}
			entry := application.entryFor(config, atmotube.Reading{})
			entry.Metadata["restored"] = true
			entry.Metadata["stale"] = true
			application.runtime.Auth.Update(config.ContainerID, application.expectedToken)
			application.registry.Set(config.ID, entry)
			application.status[config.ID] = runtimeStatus{Stale: true, LastError: "awaiting first post-restart sample"}
			if application.enablePolling {
				application.startPoller(entry)
			}
		}
	}
	return application, restoreErr
}

func (a *App) Router() *gin.Engine {
	router := gin.New()
	router.Use(gin.Logger(), gin.Recovery())
	if err := router.SetTrustedProxies(nil); err != nil {
		panic(err)
	}
	router.Use(a.requireRuntimeAuth)
	router.GET("/health", a.handleHealth)
	router.GET("/diagnostics", a.handleDiagnostics)
	router.GET("/ui", a.handleUISchema)
	router.GET("/discover", a.handleDiscover)
	router.POST("/discover", a.handleDiscover)
	router.POST("/config", a.handleConfig)
	router.POST("/configs/sync", a.handleConfigSync)
	router.POST("/config/sync", a.handleConfigSync)
	router.POST("/deconfigure", a.handleDeconfigure)
	router.GET("/state", a.handleState)
	router.GET("/events", a.handleEvents)
	router.GET("/entities", a.handleEntities)
	router.POST("/command", a.handleCommand)
	return router
}

func (a *App) handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, runtimekit.BuildRuntimeHealthResponse(
		a.runtime,
		map[string]any{
			"id":      integrationID,
			"name":    "Atmotube Pro (BLE)",
			"version": version,
		},
		map[string]any{
			"active_configs": len(a.registry.IDs()),
			"restore_error":  a.restoreError != "",
		},
	))
}

func (a *App) handleDiagnostics(c *gin.Context) {
	c.JSON(http.StatusOK, runtimekit.BuildRuntimeDiagnosticsResponse(
		a.runtime,
		map[string]any{
			"id":      integrationID,
			"name":    "Atmotube Pro (BLE)",
			"version": version,
		},
		map[string]any{
			"active_config_ids":  a.registry.IDs(),
			"recent_event_count": len(a.registry.RecentEvents()),
			"bluetooth_enabled":  true,
			"restore_error":      a.restoreError,
		},
	))
}

func (a *App) handleUISchema(c *gin.Context) {
	c.JSON(http.StatusOK, map[string]any{
		"schema": map[string]any{
			"title":       "Atmotube Pro Bluetooth Setup",
			"description": "Connect PiPhi to an Atmotube Pro by Bluetooth address and choose how often PiPhi should poll the device.",
			"type":        "object",
			"required":    []string{"address"},
			"properties": map[string]any{
				"id": map[string]any{
					"type":  "string",
					"title": "Config ID",
				},
				"address": map[string]any{
					"type":        "string",
					"title":       "Bluetooth Address",
					"description": "Atmotube Pro Bluetooth MAC address, for example 11:22:33:AA:BB:CC.",
					"examples":    []string{"11:22:33:AA:BB:CC"},
					"writeOnly":   true,
				},
				"alias": map[string]any{
					"type":        "string",
					"title":       "Alias",
					"description": "Optional name shown in PiPhi dashboards and setup flows.",
				},
				"poll_interval_seconds": map[string]any{
					"type":        "integer",
					"title":       "Poll Interval Seconds",
					"description": "How often PiPhi should reconnect to the Atmotube Pro and read fresh sensor values.",
					"default":     atmotube.DefaultPollIntervalSeconds,
					"minimum":     5,
				},
			},
		},
		"uiSchema": map[string]any{
			"address": map[string]any{
				"autocomplete": "off",
				"placeholder":  "11:22:33:AA:BB:CC",
				"help":         "Use the Bluetooth MAC address shown during discovery or from the device label.",
			},
			"alias": map[string]any{
				"placeholder": "Bedroom Atmotube",
			},
			"poll_interval_seconds": map[string]any{
				"help": "A longer interval uses less battery; 30 seconds is a good default.",
			},
		},
	})
}

func (a *App) handleDiscover(c *gin.Context) {
	inputs := map[string]any{}
	if c.Request.Method == http.MethodPost {
		var payload runtimekit.IntegrationDiscoveryRequest
		if err := c.ShouldBindJSON(&payload); err == nil && payload.Inputs != nil {
			inputs = payload.Inputs
		}
	}
	normalizedInputs := runtimekit.NormalizeDiscoveryInputs(inputs)
	log.Println(runtimekit.FormatDiscoveryAttemptLog(normalizedInputs))

	timeout := 6 * time.Second
	if rawTimeout, ok := normalizedInputs["scan_seconds"].(float64); ok && rawTimeout > 0 {
		timeout = time.Duration(rawTimeout) * time.Second
	}
	addressFilter, _ := normalizedInputs["address"].(string)

	ctx, cancel := context.WithTimeout(c.Request.Context(), timeout)
	defer cancel()

	devices, err := a.ble.Scan(ctx, timeout, addressFilter)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": publicError(err)})
		return
	}
	filtered := make([]atmotube.DiscoveredDevice, 0, len(devices))
	for _, device := range devices {
		if isAtmotubeDiscoveryMatch(device) {
			identity := opaqueDeviceID(a.identityKey, device.Address)
			device.ID = identity
			device.DeviceID = identity
			filtered = append(filtered, device)
		}
	}
	c.JSON(http.StatusOK, runtimekit.BuildDiscoveryResponse(filtered))
}

func isAtmotubeDiscoveryMatch(device atmotube.DiscoveredDevice) bool {
	name := strings.ToUpper(strings.TrimSpace(device.Name))
	return strings.Contains(name, "ATMOTUBE") || device.HasAtmotubeService
}

func (a *App) handleConfig(c *gin.Context) {
	var payload atmotube.DeviceConfig
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	payload = payload.Normalize()
	payload.ContainerID = firstNonEmpty(payload.ContainerID, runtimekit.ExtractRuntimeAuthHeaders(c.Request.Header).ContainerID)
	payload.IntegrationID = firstNonEmpty(payload.IntegrationID, integrationID)
	payload.ContainerID = firstNonEmpty(payload.ContainerID, runtimekit.ExtractRuntimeAuthHeaders(c.Request.Header).ContainerID)
	a.syncRuntimeAuth(c, payload.ContainerID)
	log.Println(runtimekit.FormatConfigApplyLog(map[string]any{
		"id":             payload.ID,
		"container_id":   payload.ContainerID,
		"integration_id": payload.IntegrationID,
		"alias":          payload.Alias,
	}))

	entry, err := a.applyConfig(payload)
	if err != nil {
		log.Printf(
			"config_apply_failed config_id=%s container_id=%s integration_id=%s error=%s",
			payload.ID,
			payload.ContainerID,
			payload.IntegrationID,
			publicError(err),
		)
		c.JSON(http.StatusBadGateway, gin.H{"error": publicError(err)})
		return
	}

	c.JSON(http.StatusOK, runtimekit.BuildConfigApplyResponse(
		entry.ConfigID,
		entry.ContainerID,
		map[string]any{
			"alias": entry.Alias,
		},
	))
}

func (a *App) handleConfigSync(c *gin.Context) {
	var payload runtimekit.RuntimeConfigSnapshot[atmotube.DeviceConfig]
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	a.syncRuntimeAuth(c, payload.ContainerID)

	response, err := a.applyConfigSnapshot(payload)
	if err != nil {
		log.Printf(
			"config_sync_failed container_id=%s generation=%d config_count=%d error=%v",
			payload.ContainerID,
			payload.Generation,
			len(payload.Configs),
			err,
		)
		c.JSON(http.StatusBadGateway, gin.H{"error": publicError(err)})
		return
	}
	c.JSON(http.StatusOK, response)
}

func (a *App) handleDeconfigure(c *gin.Context) {
	var payload struct {
		ConfigID string `json:"config_id"`
	}
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	removed := a.removeConfig(payload.ConfigID)
	c.JSON(http.StatusOK, runtimekit.BuildConfigRemoveResponse(
		payload.ConfigID,
		removed,
		map[string]any{
			"remaining_configs": len(a.registry.IDs()),
		},
	))
}

func (a *App) handleState(c *gin.Context) {
	response, err := a.state.Response(
		c.Request.Context(),
		c.Query("refresh") == "true",
		c.Query("refresh_request_id"),
	)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	payload := gin.H{
		"entries":         response.Entries,
		"state_snapshots": a.registry.StateSnapshots(),
	}
	if response.Refresh != nil {
		payload["refresh"] = response.Refresh
	}
	c.JSON(http.StatusOK, payload)
}

func (a *App) refreshAllState(_ context.Context) error {
	for _, configID := range a.registry.IDs() {
		entry, ok := a.registry.Get(configID)
		if !ok {
			continue
		}
		reading, err := a.readWithRetry(entry.Address.Reveal())
		if err != nil {
			return err
		}
		current, stillConfigured := a.registry.Get(configID)
		if !stillConfigured || current.DeviceID != entry.DeviceID {
			continue
		}
		entry = current
		entry.LatestState = reading
		a.registry.Set(entry.ConfigID, entry)
		a.state.Publish(entry.ConfigID, reading, entry.DeviceID)
		a.queueTelemetry(entry, reading)
	}
	return nil
}

func (a *App) handleEvents(c *gin.Context) {
	limit := 50
	if rawLimit := c.Query("limit"); rawLimit != "" {
		if parsed, err := strconv.Atoi(rawLimit); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	events := a.registry.RecentEvents()
	if len(events) > limit {
		events = events[len(events)-limit:]
	}
	c.JSON(http.StatusOK, runtimekit.BuildEventListResponse(events))
}

func (a *App) handleEntities(c *gin.Context) {
	entities := make([]map[string]any, 0, len(a.registry.IDs()))
	for _, entryID := range a.registry.IDs() {
		entry, ok := a.registry.Get(entryID)
		if !ok {
			continue
		}
		entities = append(entities, map[string]any{
			"id":                 entry.DeviceID,
			"name":               firstNonEmpty(entry.Alias, entry.DeviceID),
			"config_id":          entry.ConfigID,
			"device_id":          entry.DeviceID,
			"device_class":       "air-quality-sensor",
			"entity_type":        "sensor",
			"capabilities":       []string{"voc_ppb", "voc_ppm", "temperature_c", "humidity_percent", "pressure_mbar", "battery_percent", "pm1_ugm3", "pm25_ugm3", "pm4_ugm3", "pm10_ugm3", "telemetry", "refresh"},
			"available_commands": []string{"refresh"},
			"dashboard": map[string]any{
				"allowed_widgets":     []string{"stat", "line-chart", "gauge"},
				"default_widget":      "stat",
				"recommended_widgets": []string{"stat", "gauge"},
			},
			"alias":        entry.Alias,
			"latest_state": entry.LatestState,
			"operational":  a.publicStatus(entry.ConfigID),
		})
	}
	c.JSON(http.StatusOK, runtimekit.BuildEntitiesResponse(entities, nil, nil))
}

type commandRequest struct {
	Command  string         `json:"command"`
	DeviceID string         `json:"device_id,omitempty"`
	EntityID string         `json:"entity_id,omitempty"`
	Args     map[string]any `json:"args,omitempty"`
}

func (a *App) handleCommand(c *gin.Context) {
	var payload commandRequest
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if payload.Command != "refresh" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "unsupported command: " + payload.Command})
		return
	}

	configID, _ := payload.Args["config_id"].(string)
	configID = strings.TrimSpace(configID)
	var entry atmotube.DeviceEntry
	found := false
	if configID != "" {
		entry, found = a.registry.Get(configID)
	}
	if !found {
		for _, candidateID := range a.registry.IDs() {
			candidate, ok := a.registry.Get(candidateID)
			if !ok {
				continue
			}
			if candidate.DeviceID == payload.DeviceID || candidate.DeviceID == payload.EntityID {
				entry, found = candidate, true
				break
			}
		}
	}
	if !found {
		c.JSON(http.StatusNotFound, gin.H{"error": "configured Atmotube device not found"})
		return
	}

	a.syncRuntimeAuth(c, entry.ContainerID)
	reading, err := a.readWithRetry(entry.Address.Reveal())
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": publicError(err)})
		return
	}
	current, stillConfigured := a.registry.Get(entry.ConfigID)
	if !stillConfigured || current.DeviceID != entry.DeviceID {
		c.JSON(http.StatusConflict, gin.H{"error": "configured Atmotube changed during refresh"})
		return
	}
	entry = current
	entry.LatestState = reading
	a.registry.Set(entry.ConfigID, entry)
	a.registry.UpdateState(entry.ConfigID, reading)
	a.queueTelemetry(entry, reading)
	a.appendLocalEvent("atmotube.command.refresh", entry, map[string]any{
		"sampled_at": reading.SampledAt,
	})
	c.JSON(http.StatusOK, gin.H{
		"status":     "ok",
		"config_id":  entry.ConfigID,
		"device_id":  entry.DeviceID,
		"sampled_at": reading.SampledAt,
		"state":      reading,
	})
}

func (a *App) syncRuntimeAuth(c *gin.Context, payloadContainerID string) {
	parsed := adapters.SyncRuntimeAuthFromGinContext(a.runtime, c, payloadContainerID)
	log.Println(adapters.FormatRuntimeAuthSyncLogFromGinContext(c, payloadContainerID))
	_ = parsed
}

func (a *App) applyConfig(config atmotube.DeviceConfig) (atmotube.DeviceEntry, error) {
	var err error
	config, err = a.normalizeConfig(config)
	if err != nil {
		return atmotube.DeviceEntry{}, err
	}
	reading, err := a.readWithRetry(config.Address.Reveal())
	if err != nil {
		return atmotube.DeviceEntry{}, err
	}
	entry := a.entryFor(config, reading)

	a.configMu.Lock()
	defer a.configMu.Unlock()
	configs := a.currentConfigs()
	configs[config.ID] = config
	if err := a.persistConfigs(configs); err != nil {
		return atmotube.DeviceEntry{}, err
	}
	a.registry.Set(config.ID, entry)
	a.registry.UpdateState(config.ID, reading)
	a.appendLocalEvent("atmotube.config.applied", entry, map[string]any{
		"alias": config.Alias,
	})
	a.recordSuccess(entry, reading)
	if a.enablePolling {
		a.startPoller(entry)
	}
	return entry, nil
}

func (a *App) removeConfig(configID string) bool {
	a.configMu.Lock()
	defer a.configMu.Unlock()
	if _, exists := a.registry.Get(configID); !exists {
		return false
	}
	configs := a.currentConfigs()
	delete(configs, configID)
	if err := a.persistConfigs(configs); err != nil {
		log.Printf("config_remove_persist_failed config_id=%s error=%s", configID, publicError(err))
		return false
	}
	return a.removeConfigCommitted(configID)
}

func (a *App) removeConfigCommitted(configID string) bool {
	a.mu.Lock()
	cancel, ok := a.pollers[configID]
	if ok {
		delete(a.pollers, configID)
	}
	a.mu.Unlock()
	if ok {
		cancel()
	}

	entry, removed := a.registry.Remove(configID)
	if removed {
		a.mu.Lock()
		delete(a.status, configID)
		a.mu.Unlock()
		a.appendLocalEvent("atmotube.config.removed", entry, nil)
	}
	return removed
}

func (a *App) startPoller(entry atmotube.DeviceEntry) {
	a.mu.Lock()
	if existing, ok := a.pollers[entry.ConfigID]; ok {
		existing()
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.pollers[entry.ConfigID] = cancel
	a.mu.Unlock()

	runtimekit.CreateTrackedTask(a.runtime.ProcessState, func() {
		ticker := time.NewTicker(entry.Config.PollInterval())
		defer ticker.Stop()

		for {
			a.pollOnce(entry)

			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
		}
	})
}

func (a *App) pollOnce(entry atmotube.DeviceEntry) {
	reading, err := a.readWithRetry(entry.Address.Reveal())
	if err != nil {
		current, stillConfigured := a.registry.Get(entry.ConfigID)
		if !stillConfigured || current.DeviceID != entry.DeviceID {
			return
		}
		entry = current
		a.recordFailure(entry, err)
		return
	}
	current, stillConfigured := a.registry.Get(entry.ConfigID)
	if !stillConfigured || current.DeviceID != entry.DeviceID {
		return
	}
	entry = current

	entry.LatestState = reading
	a.registry.Set(entry.ConfigID, entry)
	a.registry.UpdateState(entry.ConfigID, reading)
	a.recordSuccess(entry, reading)
	a.queueTelemetry(entry, reading)
}

func (a *App) queueTelemetry(entry atmotube.DeviceEntry, reading atmotube.Reading) {
	payload := runtimekit.TelemetryPayload{
		DeviceID:      entry.DeviceID,
		ConfigID:      entry.ConfigID,
		ContainerID:   entry.ContainerID,
		IntegrationID: entry.IntegrationID,
		Metrics: map[string]any{
			"voc_ppb":          reading.VOCPPB,
			"voc_ppm":          reading.VOCPPM,
			"humidity_percent": reading.HumidityPercent,
			"temperature_c":    reading.TemperatureC,
			"pressure_mbar":    reading.PressureMbar,
			"battery_percent":  reading.BatteryPercent,
			"pm1_ugm3":         reading.PM1UGM3,
			"pm25_ugm3":        reading.PM25UGM3,
			"pm4_ugm3":         reading.PM4UGM3,
			"pm10_ugm3":        reading.PM10UGM3,
		},
		Units: map[string]any{
			"voc_ppb":          "ppb",
			"voc_ppm":          "ppm",
			"humidity_percent": "%",
			"temperature_c":    "C",
			"pressure_mbar":    "mbar",
			"battery_percent":  "%",
			"pm1_ugm3":         "ug/m3",
			"pm25_ugm3":        "ug/m3",
			"pm4_ugm3":         "ug/m3",
			"pm10_ugm3":        "ug/m3",
		},
		Timestamp: reading.SampledAt,
	}

	log.Printf(
		"telemetry_queue config_id=%s device_id=%s container_id=%s integration_id=%s metric_count=%d sampled_at=%s",
		entry.ConfigID,
		entry.DeviceID,
		entry.ContainerID,
		entry.IntegrationID,
		len(payload.Metrics),
		payload.Timestamp,
	)

	runtimekit.CreateTrackedTask(a.runtime.ProcessState, func() {
		if err := a.telemetry.SendMetrics(a.runtime.Auth, payload); err != nil {
			log.Printf(
				"telemetry_delivery_failed config_id=%s device_id=%s container_id=%s integration_id=%s metric_count=%d error=%v",
				entry.ConfigID,
				entry.DeviceID,
				entry.ContainerID,
				entry.IntegrationID,
				len(payload.Metrics),
				err,
			)
			a.appendLocalEvent("atmotube.telemetry.error", entry, map[string]any{
				"error":        publicError(err),
				"metric_count": len(payload.Metrics),
			})
			return
		}

		log.Printf(
			"telemetry_delivery_succeeded config_id=%s device_id=%s container_id=%s integration_id=%s metric_count=%d",
			entry.ConfigID,
			entry.DeviceID,
			entry.ContainerID,
			entry.IntegrationID,
			len(payload.Metrics),
		)
	})
}

func (a *App) appendLocalEvent(eventType string, entry atmotube.DeviceEntry, payload map[string]any) {
	event := runtimekit.BuildLocalEventRecord(map[string]any{
		"event_type":     eventType,
		"source":         "piphi-network-atmotube",
		"severity":       "info",
		"device_id":      entry.DeviceID,
		"config_id":      entry.ConfigID,
		"container_id":   entry.ContainerID,
		"integration_id": entry.IntegrationID,
		"payload":        redactRecursive(payload),
	})
	a.registry.AppendEvent(event)
}

func (a *App) normalizeConfig(config atmotube.DeviceConfig) (atmotube.DeviceConfig, error) {
	config = config.Normalize()
	address := config.Address.Reveal()
	parsed, err := net.ParseMAC(address)
	if err != nil || len(parsed) != 6 {
		return atmotube.DeviceConfig{}, fmt.Errorf("invalid Bluetooth address")
	}
	if config.PollIntervalSeconds < 5 || config.PollIntervalSeconds > 3600 {
		return atmotube.DeviceConfig{}, fmt.Errorf("poll_interval_seconds must be between 5 and 3600")
	}
	identity := opaqueDeviceID(a.identityKey, address)
	if strings.TrimSpace(config.ID) == "" || strings.EqualFold(strings.TrimSpace(config.ID), address) || macPattern.MatchString(config.ID) {
		config.ID = identity
	}
	config.ConfigID = config.ID
	config.DeviceID = identity
	config.IntegrationID = firstNonEmpty(config.IntegrationID, integrationID)
	return config, nil
}

func (a *App) entryFor(config atmotube.DeviceConfig, reading atmotube.Reading) atmotube.DeviceEntry {
	return atmotube.DeviceEntry{
		ConfigID: config.ID, DeviceID: config.DeviceID, ContainerID: config.ContainerID,
		IntegrationID: config.IntegrationID, Address: config.Address, Alias: config.Alias,
		Config: config, LatestState: reading,
		Metadata: map[string]any{"poll_interval_seconds": config.PollIntervalSeconds},
	}
}

func (a *App) readWithRetry(address string) (atmotube.Reading, error) {
	var lastErr error
	for attempt := 1; attempt <= 3; attempt++ {
		reading, err := a.ble.ReadSnapshot(address)
		if err == nil {
			return reading, nil
		}
		lastErr = err
		if attempt < 3 {
			time.Sleep(time.Duration(attempt) * 50 * time.Millisecond)
		}
	}
	return atmotube.Reading{}, fmt.Errorf("BLE snapshot unavailable after 3 attempts: %s", publicError(lastErr))
}

func (a *App) currentConfigs() map[string]atmotube.DeviceConfig {
	configs := make(map[string]atmotube.DeviceConfig, len(a.registry.IDs()))
	for _, id := range a.registry.IDs() {
		if entry, ok := a.registry.Get(id); ok {
			configs[id] = entry.Config
		}
	}
	return configs
}

func (a *App) persistConfigs(configs map[string]atmotube.DeviceConfig) error {
	if a.store == nil {
		return nil
	}
	ids := make([]string, 0, len(configs))
	for id := range configs {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	state := persistedState{SchemaVersion: 1, IdentityKey: encodeIdentityKey(a.identityKey)}
	for _, id := range ids {
		state.Configs = append(state.Configs, persistedFromConfig(configs[id]))
	}
	return a.store.Save(state)
}

func (a *App) applyConfigSnapshot(payload runtimekit.RuntimeConfigSnapshot[atmotube.DeviceConfig]) (runtimekit.RuntimeConfigSyncResponse, error) {
	prepared := make(map[string]atmotube.DeviceEntry, len(payload.Configs))
	configs := make(map[string]atmotube.DeviceConfig, len(payload.Configs))
	for _, candidate := range payload.Configs {
		if candidate.ContainerID == "" {
			candidate.ContainerID = payload.ContainerID
		}
		if candidate.IntegrationID == "" {
			candidate.IntegrationID = payload.IntegrationID
		}
		config, err := a.normalizeConfig(candidate)
		if err != nil {
			return runtimekit.RuntimeConfigSyncResponse{}, err
		}
		if _, duplicate := prepared[config.ID]; duplicate {
			return runtimekit.RuntimeConfigSyncResponse{}, fmt.Errorf("duplicate config_id %q", config.ID)
		}
		reading, err := a.readWithRetry(config.Address.Reveal())
		if err != nil {
			return runtimekit.RuntimeConfigSyncResponse{}, err
		}
		prepared[config.ID] = a.entryFor(config, reading)
		configs[config.ID] = config
	}

	a.configMu.Lock()
	defer a.configMu.Unlock()
	oldIDs := a.registry.IDs()
	if err := a.persistConfigs(configs); err != nil {
		return runtimekit.RuntimeConfigSyncResponse{}, err
	}
	oldSet := make(map[string]bool, len(oldIDs))
	for _, id := range oldIDs {
		oldSet[id] = true
	}
	response := runtimekit.RuntimeConfigSyncResponse{OK: true, Generation: payload.Generation, AppliedConfigIDs: []string{}, RemovedConfigIDs: []string{}, SkippedConfigIDs: []string{}}
	for _, id := range oldIDs {
		if _, retained := prepared[id]; !retained {
			a.removeConfigCommitted(id)
			response.RemovedConfigIDs = append(response.RemovedConfigIDs, id)
		}
	}
	ids := make([]string, 0, len(prepared))
	for id := range prepared {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		entry := prepared[id]
		a.registry.Set(id, entry)
		a.registry.UpdateState(id, entry.LatestState)
		a.recordSuccess(entry, entry.LatestState)
		if a.enablePolling {
			a.startPoller(entry)
		}
		if oldSet[id] {
			response.SkippedConfigIDs = append(response.SkippedConfigIDs, id)
		} else {
			response.AppliedConfigIDs = append(response.AppliedConfigIDs, id)
		}
	}
	return response, nil
}

func (a *App) recordFailure(entry atmotube.DeviceEntry, err error) {
	a.mu.Lock()
	status := a.status[entry.ConfigID]
	wasStale := status.Stale
	status.ConsecutiveFailures++
	status.LastError = publicError(err)
	if status.ConsecutiveFailures >= 2 || (!status.LastSuccess.IsZero() && time.Since(status.LastSuccess) > 3*entry.Config.PollInterval()) {
		status.Stale = true
	}
	a.status[entry.ConfigID] = status
	a.mu.Unlock()
	if status.Stale && !wasStale {
		a.appendLocalEvent("atmotube.connection.stale", entry, map[string]any{"failures": status.ConsecutiveFailures, "error": status.LastError})
	}
}

func (a *App) recordSuccess(entry atmotube.DeviceEntry, reading atmotube.Reading) {
	a.mu.Lock()
	status := a.status[entry.ConfigID]
	wasStale := status.Stale
	status.LastSuccess = time.Now().UTC()
	status.ConsecutiveFailures = 0
	status.Stale = false
	status.LastError = ""
	a.status[entry.ConfigID] = status
	a.mu.Unlock()
	if wasStale {
		a.appendLocalEvent("atmotube.connection.recovered", entry, map[string]any{"sampled_at": reading.SampledAt})
	}
}

func (a *App) publicStatus(configID string) map[string]any {
	a.mu.Lock()
	defer a.mu.Unlock()
	status := a.status[configID]
	result := map[string]any{
		"stale": status.Stale, "consecutive_failures": status.ConsecutiveFailures,
	}
	if !status.LastSuccess.IsZero() {
		result["last_success_at"] = status.LastSuccess.Format(time.RFC3339)
	}
	if status.LastError != "" {
		result["last_error"] = status.LastError
	}
	return result
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
