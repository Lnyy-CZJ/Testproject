package main

import (
	"bug-agent/internal/model"
	"reflect"
	"testing"
)

func TestMigrationModels_IncludeCollaborationTables(t *testing.T) {
	models := migrationModels()

	hasTask := false
	hasReport := false
	for _, item := range models {
		switch reflect.TypeOf(item) {
		case reflect.TypeOf(&model.CollaborationTask{}):
			hasTask = true
		case reflect.TypeOf(&model.CollaborationReport{}):
			hasReport = true
		}
	}

	if !hasTask {
		t.Fatal("migration models should include CollaborationTask")
	}
	if !hasReport {
		t.Fatal("migration models should include CollaborationReport")
	}
}
