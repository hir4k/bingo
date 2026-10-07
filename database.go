package bingo

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

type DatabaseConfig struct {
	Driver   string
	Database string
}

// Database registers the application's typed configuration function. It runs at
// execution time so environment values are never captured by a production build.
func (a *App) Database(configure func(string) (DatabaseConfig, error)) {
	a.root.mutable()
	if a.commands.frozen {
		panic("bingo: database configuration is frozen after execution")
	}
	if configure == nil {
		panic("bingo: database configuration cannot be nil")
	}
	if a.database != nil {
		panic("bingo: database configuration is already registered")
	}
	a.database = configure
}

// DatabaseSettings resolves paths against the app directory for both server and
// commands. Configuration code selects environments; Bingo validates the driver.
func (a *App) DatabaseSettings(environment string) (DatabaseConfig, error) {
	if a.database == nil {
		return DatabaseConfig{}, fmt.Errorf("register database configuration with app.Database")
	}
	config, err := a.database(environment)
	if err != nil {
		return DatabaseConfig{}, err
	}
	if config.Driver != "sqlite" || config.Database == "" {
		return DatabaseConfig{}, fmt.Errorf("only sqlite with a database path is supported")
	}
	if !filepath.IsAbs(config.Database) {
		config.Database = filepath.Join(a.Directory, config.Database)
	}
	return config, nil
}

// SQLite uses one pooled connection to avoid competing writers. Busy timeout and
// foreign keys are configured on every connection through the driver's DSN.
// Immediate transactions acquire the writer lock before reading, preventing
// read-to-write upgrade races between server and worker processes.
// GORM remains a native *gorm.DB; Bingo never calls AutoMigrate.
func OpenDatabase(config DatabaseConfig) (*gorm.DB, error) {
	if config.Driver != "sqlite" {
		return nil, fmt.Errorf("unsupported database driver %q", config.Driver)
	}
	if config.Database == "" {
		return nil, fmt.Errorf("database path cannot be empty")
	}
	var err error
	config.Database, err = filepath.Abs(config.Database)
	if err != nil {
		return nil, err
	}
	err = os.MkdirAll(filepath.Dir(config.Database), 0755)
	if err != nil {
		return nil, err
	}
	var location url.URL = url.URL{Scheme: "file", Path: filepath.ToSlash(config.Database)}
	var dsn string = location.String() + "?_foreign_keys=on&_busy_timeout=5000&_txlock=immediate"
	var db *gorm.DB
	db, err = gorm.Open(sqlite.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if err != nil {
		return nil, err
	}
	var pool, poolError = db.DB()
	if poolError != nil {
		return nil, poolError
	}
	pool.SetMaxOpenConns(1)
	pool.SetMaxIdleConns(1)
	return db, nil
}
