package app

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"net/http"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
)

const runtimeTokenHeader = "X-PiPhi-Integration-Token"

var macPattern = regexp.MustCompile(`(?i)\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b`)

func (a *App) requireRuntimeAuth(c *gin.Context) {
	if c.Request.URL.Path == "/health" {
		c.Next()
		return
	}
	if a.restoreError != "" {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"detail": "persisted runtime state could not be restored"})
		return
	}
	if a.expectedToken == "" {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"detail": "runtime authentication is not configured"})
		return
	}
	provided := strings.TrimSpace(c.GetHeader(runtimeTokenHeader))
	if len(provided) != len(a.expectedToken) || subtle.ConstantTimeCompare([]byte(provided), []byte(a.expectedToken)) != 1 {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "invalid runtime authentication"})
		return
	}
	c.Next()
}

func opaqueDeviceID(key []byte, address string) string {
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte("piphi-network-atmotube\x00" + strings.ToUpper(strings.TrimSpace(address))))
	return "atm_" + hex.EncodeToString(mac.Sum(nil)[:12])
}

func redactText(value string) string {
	return macPattern.ReplaceAllString(value, "[redacted-device-address]")
}

func redactRecursive(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		result := make(map[string]any, len(typed))
		for key, item := range typed {
			lower := strings.ToLower(key)
			if strings.Contains(lower, "address") || strings.Contains(lower, "token") || strings.Contains(lower, "secret") || strings.Contains(lower, "password") || strings.Contains(lower, "key") {
				result[key] = "[redacted]"
				continue
			}
			result[key] = redactRecursive(item)
		}
		return result
	case []any:
		result := make([]any, len(typed))
		for index, item := range typed {
			result[index] = redactRecursive(item)
		}
		return result
	case string:
		return redactText(typed)
	case error:
		return redactText(typed.Error())
	default:
		return value
	}
}

func publicError(err error) string {
	if err == nil {
		return ""
	}
	return fmt.Sprint(redactRecursive(err))
}
