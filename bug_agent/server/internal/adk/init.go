package adk

import (
	"fmt"
	"sync"

	"gorm.io/gorm"

	"bug-agent/internal/retrieval"

	"google.golang.org/adk/session"
	sessiondb "google.golang.org/adk/session/database"
)

var GlobalRegistry *retrieval.RetrieverPluginRegistry
var registryOnce sync.Once

func InitRegistry() {
	registryOnce.Do(func() {
		GlobalRegistry = retrieval.NewRetrieverPluginRegistry()
		retrieval.RegisterBuiltinPlugins(GlobalRegistry)
	})
}

func InitSessionService(db *gorm.DB) (session.Service, error) {
	if db == nil {
		return nil, fmt.Errorf("db is nil")
	}
	svc, err := sessiondb.NewSessionService(db.Dialector, &gorm.Config{})
	if err != nil {
		return nil, fmt.Errorf("sessiondb.NewSessionService: %w", err)
	}
	if err := sessiondb.AutoMigrate(svc); err != nil {
		return nil, fmt.Errorf("sessiondb.AutoMigrate: %w", err)
	}
	return svc, nil
}
