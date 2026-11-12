package app

import (
	"context"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	runtimekit "github.com/PiPhi-io/piphi-runtime-kit-go"
	"github.com/PiPhi-io/piphi-runtime-kit-go/adapters"

	"github.com/KelvinSan/piphi-network-atmotube/atmotube"
)

const integrationID = "piphi-network-atmotube-pro"

type App struct {
	runtime       *runtimekit.RuntimeContext
	registry      *runtimekit.RuntimeRegistry[atmotube.DeviceEntry, atmotube.Reading, map[string]any]
	state         *runtimekit.RuntimeStateService[atmotube.DeviceEntry, atmotube.Reading, map[string]any]
	telemetry     *runtimekit.TelemetryClient
	coordinator   *runtimekit.ConfigSyncCoordinator[atmotube.DeviceConfig]
	ble           BLEClient
	enablePolling bool

	mu      sync.Mutex
	pollers map[string]context.CancelFunc
}

type BLEClient interface {
	Scan(ctx context.Context, timeout time.Duration, addressFilter string) ([]atmotube.DiscoveredDevice, error)
	ReadSnapshot(address string) (atmotube.Reading, error)
}

func New() *App {
	return NewWithOptions(atmotube.NewClient(), true)
}

func NewWithOptions(ble BLEClient, enablePolling bool) *App {
	runtime := runtimekit.NewRuntimeContext()
	registry := runtimekit.NewRuntimeRegistry[atmotube.DeviceEntry, atmotube.Reading, map[string]any](100)
	application := &App{
		runtime:       runtime,
		registry:      registry,
		state:         runtimekit.NewRuntimeStateService(registry),
		telemetry:     runtimekit.NewTelemetryClient(runtime.ProcessState, "", 0),
		coordinator:   runtimekit.NewConfigSyncCoordinator[atmotube.DeviceConfig](runtime.ProcessState),
		ble:           ble,
		enablePolling: enablePolling,
		pollers:       map[string]context.CancelFunc{},
	}
	if err := application.state.Provide(application.refreshAllState, integrationID); err != nil {
		panic(err)
	}
	return application
}

func (a *App) Router() *gin.Engine {
	router := gin.Default()
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
			"version": "0.1.0",
		},
		map[string]any{
			"active_configs": len(a.registry.IDs()),
		},
	))
}

func (a *App) handleDiagnostics(c *gin.Context) {
	c.JSON(http.StatusOK, runtimekit.BuildRuntimeDiagnosticsResponse(
		a.runtime,
		map[string]any{
			"id":      integrationID,
			"name":    "Atmotube Pro (BLE)",
			"version": "0.1.0",
		},
		map[string]any{
			"active_config_ids":  a.registry.IDs(),
			"recent_event_count": len(a.registry.RecentEvents()),
			"bluetooth_enabled":  true,
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
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
	filtered := make([]atmotube.DiscoveredDevice, 0, len(devices))
	for _, device := range devices {
		if isAtmotubeDiscoveryMatch(device) {
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
	payload.IntegrationID = firstNonEmpty(payload.IntegrationID, integrationID)
	a.syncRuntimeAuth(c, payload.ContainerID)
	log.Println(runtimekit.FormatConfigApplyLog(map[string]any{
		"id":             payload.ID,
		"container_id":   payload.ContainerID,
		"integration_id": payload.IntegrationID,
		"address":        payload.Address,
		"alias":          payload.Alias,
	}))

	entry, err := a.applyConfig(payload)
	if err != nil {
		log.Printf(
			"config_apply_failed config_id=%s container_id=%s integration_id=%s address=%s error=%v",
			payload.ID,
			payload.ContainerID,
			payload.IntegrationID,
			payload.Address,
			err,
		)
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, runtimekit.BuildConfigApplyResponse(
		entry.ConfigID,
		entry.ContainerID,
		map[string]any{
			"address": entry.Address,
			"alias":   entry.Alias,
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

	for index := range payload.Configs {
		payload.Configs[index] = payload.Configs[index].Normalize()
	}

	response, err := a.coordinator.ApplySnapshot(
		payload,
		a.registry.IDs(),
		func(config atmotube.DeviceConfig) error {
			_, applyErr := a.applyConfig(config)
			return applyErr
		},
		func(configID string) (bool, error) {
			return a.removeConfig(configID), nil
		},
		func() []string {
			return a.registry.IDs()
		},
	)
	if err != nil {
		log.Printf(
			"config_sync_failed container_id=%s generation=%d config_count=%d error=%v",
			payload.ContainerID,
			payload.Generation,
			len(payload.Configs),
			err,
		)
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
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
		reading, err := a.ble.ReadSnapshot(entry.Address)
		if err != nil {
			return err
		}
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
			"id":           entry.DeviceID,
			"name":         firstNonEmpty(entry.Alias, entry.DeviceID),
			"config_id":    entry.ConfigID,
			"device_id":    entry.DeviceID,
			"device_class": "air-quality-sensor",
			"entity_type":  "sensor",
			"capabilities": []string{"voc_ppb", "temperature_c", "humidity_percent", "pressure_mbar", "battery_percent", "pm25_ugm3", "telemetry"},
			"dashboard": map[string]any{
				"allowed_widgets":     []string{"stat", "line-chart", "gauge"},
				"default_widget":      "stat",
				"recommended_widgets": []string{"stat", "gauge"},
			},
			"address":      entry.Address,
			"alias":        entry.Alias,
			"latest_state": entry.LatestState,
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
	reading, err := a.ble.ReadSnapshot(entry.Address)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
		return
	}
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
	config = config.Normalize()
	reading, err := a.ble.ReadSnapshot(config.Address)
	if err != nil {
		return atmotube.DeviceEntry{}, err
	}

	entry := atmotube.DeviceEntry{
		ConfigID:      config.ID,
		DeviceID:      config.DeviceID,
		ContainerID:   config.ContainerID,
		IntegrationID: firstNonEmpty(config.IntegrationID, integrationID),
		Address:       config.Address,
		Alias:         config.Alias,
		Config:        config,
		LatestState:   reading,
		Metadata: map[string]any{
			"poll_interval_seconds": config.PollIntervalSeconds,
		},
	}
	a.registry.Set(config.ID, entry)
	a.registry.UpdateState(config.ID, reading)
	a.appendLocalEvent("atmotube.config.applied", entry, map[string]any{
		"address": config.Address,
		"alias":   config.Alias,
	})
	if a.enablePolling {
		a.startPoller(entry)
	}
	return entry, nil
}

func (a *App) removeConfig(configID string) bool {
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
	reading, err := a.ble.ReadSnapshot(entry.Address)
	if err != nil {
		a.appendLocalEvent("atmotube.poll.error", entry, map[string]any{
			"error": err.Error(),
		})
		return
	}

	entry.LatestState = reading
	a.registry.Set(entry.ConfigID, entry)
	a.registry.UpdateState(entry.ConfigID, reading)

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
				"error":        err.Error(),
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
		"payload":        payload,
	})
	a.registry.AppendEvent(event)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
