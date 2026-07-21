package adk

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"bug-agent/internal/ai"
	bugmodel "bug-agent/internal/model"

	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/model/gemini"
	"google.golang.org/genai"
)

var (
	fcCache     map[string]bool
	fcCacheMu   sync.RWMutex
	fcCacheTime time.Time
)

const fcCacheTTL = 5 * time.Minute

func NewLLM(ctx context.Context, cfg *bugmodel.ProjectAIConfig) (adkmodel.LLM, error) {
	if cfg.Provider == "gemini" {
		return gemini.NewModel(ctx, cfg.ModelName, &genai.ClientConfig{
			APIKey: cfg.APIKey,
		})
	}

	client, err := ai.NewAIClient(cfg.Provider, cfg.APIKey, cfg.APIEndpoint, cfg.ModelName)
	if err != nil {
		return nil, fmt.Errorf("NewAIClient(%s): %w", cfg.Provider, err)
	}

	supportsFC := resolveFCSupport(cfg)
	return NewAIClientModelWithFC(client, cfg.ModelName, supportsFC), nil
}

func resolveFCSupport(cfg *bugmodel.ProjectAIConfig) bool {
	mode := cfg.FunctionCallingMode
	if mode == "" {
		mode = "auto"
	}

	switch mode {
	case "enabled":
		return true
	case "disabled":
		return false
	case "auto":
		fallthrough
	default:
		return checkModelFCCapability(cfg.Provider, cfg.ModelName)
	}
}

func checkModelFCCapability(provider, modelName string) bool {
	key := provider + "/" + modelName

	fcCacheMu.RLock()
	if fcCache != nil && time.Since(fcCacheTime) < fcCacheTTL {
		if v, ok := fcCache[key]; ok {
			fcCacheMu.RUnlock()
			return v
		}
	}
	fcCacheMu.RUnlock()

	result := queryModelFCCapability(provider, modelName)

	fcCacheMu.Lock()
	if fcCache == nil {
		fcCache = make(map[string]bool)
	}
	fcCache[key] = result
	fcCacheTime = time.Now()
	fcCacheMu.Unlock()

	return result
}

func queryModelFCCapability(provider, modelName string) bool {
	if bugmodel.DB == nil {
		return true
	}

	var catalog []bugmodel.AIModelCatalog
	if err := bugmodel.DB.Where("provider_key = ? AND model_name = ? AND status = 'active'", provider, modelName).Find(&catalog).Error; err != nil {
		return true
	}

	if len(catalog) == 0 {
		return true
	}

	tags := catalog[0].CapabilityTags
	if tags == "" {
		return true
	}

	for _, tag := range strings.Split(tags, ",") {
		if strings.TrimSpace(tag) == "fc" {
			return true
		}
	}

	return false
}

func InvalidateFCCache() {
	fcCacheMu.Lock()
	fcCache = nil
	fcCacheMu.Unlock()
}
