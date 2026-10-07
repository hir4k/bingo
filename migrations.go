package bingo

import (
	"context"
	"fmt"
	"io"
	"io/fs"
	"path/filepath"

	"github.com/pressly/goose/v3"
)

// Goose's provider keeps dialect and migration state local to this invocation.
// App and CLI both open SQLite through Bingo's shared configuration and driver.
func runMigrations(ctx context.Context, config DatabaseConfig, migrations fs.FS, command string, output io.Writer) error {
	var err error
	var db, openError = OpenDatabase(config)
	if openError != nil {
		return openError
	}
	var pool, poolError = db.DB()
	if poolError != nil {
		return poolError
	}
	defer pool.Close()
	var provider *goose.Provider
	provider, err = goose.NewProvider(goose.DialectSQLite3, pool, migrations, goose.WithDisableGlobalRegistry(true))
	if err != nil {
		return err
	}
	switch command {
	case "migrate":
		var results []*goose.MigrationResult
		results, err = provider.Up(ctx)
		for _, result := range results {
			fmt.Fprintln(output, result)
		}
		if err == nil && len(results) == 0 {
			fmt.Fprintln(output, "No pending migrations.")
		}
	case "rollback":
		var result *goose.MigrationResult
		result, err = provider.Down(ctx)
		if err == nil {
			fmt.Fprintln(output, result)
		}
	case "status":
		var statuses []*goose.MigrationStatus
		statuses, err = provider.Status(ctx)
		for _, status := range statuses {
			fmt.Fprintf(output, "%d\t%s\t%s\n", status.Source.Version, status.State, filepath.Base(status.Source.Path))
		}
	case "version":
		var version int64
		version, err = provider.GetDBVersion(ctx)
		if err == nil {
			fmt.Fprintln(output, version)
		}
	default:
		return fmt.Errorf("unknown database command %q", command)
	}
	return err
}
