package project

import (
	"context"
	"io"
)

// Test helpers and development execution share the application's Goose dispatcher.
func Migrate(ctx context.Context, root string, environment string, command string, output io.Writer) error {
	return RunCommand(ctx, root, []string{"db", command, "--env", environment}, nil, output, output)
}
