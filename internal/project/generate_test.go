package project

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/hir4k/bingo"
)

func newProject(t *testing.T) string {
	t.Helper()
	var directory string = filepath.Join(t.TempDir(), "app")
	if err := New(directory, "example.com/app", frameworkRoot(t)); err != nil {
		t.Fatal(err)
	}
	return directory
}

// Exercise the generated schema through Goose and GORM, including rollback.
// This checks their integration instead of matching SQL strings to templates.
func TestModelMigrationLifecycle(t *testing.T) {
	var root string = newProject(t)
	if err := GenerateModel(root, "Task", []string{"name:string", "completed:bool", "count:integer", "select:string"}); err != nil {
		t.Fatal(err)
	}
	if _, err := GenerateMigration(root, "add_priority_to_tasks", []string{"priority:integer"}); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	var ctx context.Context = context.Background()
	if err := Migrate(ctx, root, "test", "status", &output); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "pending") {
		t.Fatal(output.String())
	}
	output.Reset()
	if err := Migrate(ctx, root, "test", "migrate", &output); err != nil {
		t.Fatal(err)
	}
	var config bingo.DatabaseConfig
	config = bingo.DatabaseConfig{Driver: "sqlite", Database: filepath.Join(root, "database/test.sqlite3")}
	db, err := bingo.OpenDatabase(config)
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	if !db.Migrator().HasColumn("tasks", "priority") {
		t.Fatal("missing generated column")
	}
	if err = db.Exec("INSERT INTO tasks (name,completed,count,priority) VALUES (?, ?, ?, ?)", "Task", false, 0, 2).Error; err != nil {
		t.Fatal(err)
	}
	_ = pool.Close()
	output.Reset()
	if err = Migrate(ctx, root, "test", "version", &output); err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(output.String()) != "3" {
		t.Fatalf("version: %s", output.String())
	}
	if err = Migrate(ctx, root, "test", "rollback", &output); err != nil {
		t.Fatal(err)
	}
	db, err = bingo.OpenDatabase(config)
	if err != nil {
		t.Fatal(err)
	}
	pool, _ = db.DB()
	defer pool.Close()
	if db.Migrator().HasColumn("tasks", "priority") {
		t.Fatal("rollback did not remove column")
	}
	var count int64
	if err = db.Table("tasks").Count(&count).Error; err != nil || count != 1 {
		t.Fatalf("rollback lost record: %d %v", count, err)
	}
}

func TestGenerationCollisionsAndInvalidFields(t *testing.T) {
	var root string = newProject(t)
	if err := GenerateModel(root, "Task", []string{"name:string"}); err != nil {
		t.Fatal(err)
	}
	var modelPath string = filepath.Join(root, "models/task.go")
	var original []byte
	original, _ = os.ReadFile(modelPath)
	if err := GenerateModel(root, "Task", []string{"name:string"}); err == nil {
		t.Fatal("duplicate model accepted")
	}
	var after []byte
	after, _ = os.ReadFile(modelPath)
	if !bytes.Equal(original, after) {
		t.Fatal("overwrote model")
	}
	for _, arguments := range [][]string{{"id:integer"}, {"name:string", "name:bool"}, {"value:unknown"}, {"sql;drop:string"}} {
		if err := GenerateModel(root, "Bad", arguments); err == nil {
			t.Fatalf("accepted %v", arguments)
		}
	}
	if _, err := os.Stat(filepath.Join(root, "models/bad.go")); !os.IsNotExist(err) {
		t.Fatal("partial invalid generation")
	}
	if err := GenerateController(root, "Reports"); err != nil {
		t.Fatal(err)
	}
	if err := GenerateController(root, "Reports"); err == nil {
		t.Fatal("duplicate controller accepted")
	}
}

func TestUnfinishedMigrationCannotApply(t *testing.T) {
	var root string = newProject(t)
	var inferred bool
	var err error
	inferred, err = GenerateMigration(root, "custom_operation", nil)
	if err != nil || inferred {
		t.Fatalf("skeleton: %v", err)
	}
	var output bytes.Buffer
	err = Migrate(context.Background(), root, "test", "migrate", &output)
	if err == nil {
		t.Fatal("applied an unfinished migration")
	}
	output.Reset()
	if err = Migrate(context.Background(), root, "test", "version", &output); err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(output.String()) != "1" {
		t.Fatalf("unfinished migration marked applied: %s", output.String())
	}
}

func TestGeneratorLockProtectsVersionAllocation(t *testing.T) {
	var root string = newProject(t)
	var release func()
	var err error
	release, err = generationLock(root)
	if err != nil {
		t.Fatal(err)
	}
	if err = GenerateModel(root, "Task", []string{"name:string"}); err == nil {
		t.Fatal("ignored active generator lock")
	}
	release()
	if err = GenerateModel(root, "Task", []string{"name:string"}); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(root, ".bingo-generation.lock")); !os.IsNotExist(err) {
		t.Fatal("lock was not released")
	}
}

func TestNewIncludesJobQueueMigration(t *testing.T) {
	root := newProject(t)
	files, err := filepath.Glob(filepath.Join(root, "database/migrations/*.sql"))
	if err != nil || len(files) != 1 || filepath.Base(files[0]) != "000001_create_bingo_jobs.sql" {
		t.Fatalf("default migrations: %v %v", files, err)
	}
	var output bytes.Buffer
	if err := Migrate(context.Background(), root, "test", "migrate", &output); err != nil {
		t.Fatal(err)
	}
	db, err := bingo.OpenDatabase(bingo.DatabaseConfig{Driver: "sqlite", Database: filepath.Join(root, "database/test.sqlite3")})
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	defer pool.Close()
	for _, table := range []string{"goqite", "bingo_jobs", "bingo_schedules"} {
		if !db.Migrator().HasTable(table) {
			t.Fatalf("missing queue table %s", table)
		}
	}
	if _, err := GenerateMigration(root, "create_bingo_jobs", nil); err == nil {
		t.Fatal("duplicate queue migration accepted")
	}
}
