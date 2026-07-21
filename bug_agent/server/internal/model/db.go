package model

import (
	"sync"

	"gorm.io/gorm"
)

var (
	db     *gorm.DB
	dbOnce sync.Once
)

func SetDB(instance *gorm.DB) {
	dbOnce.Do(func() {
		db = instance
		DB = instance
	})
}

func GetDB() *gorm.DB {
	return db
}

// DB is kept for backward compatibility. Prefer GetDB() for new code.
var DB *gorm.DB
