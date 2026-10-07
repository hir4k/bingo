package bingo

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestCommandRegistrationRules(t *testing.T) {
	handler := func(*CommandContext) error { return nil }
	for _, name := range []string{"db", "build", "new", "worker", "BadName", "two words", "todo-count", "_count", "count_", "todo__count", ""} {
		t.Run(name, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Fatal("registration accepted invalid name")
				}
			}()
			New().Commands(func(c *Commands) { c.Register(name, "description", handler) })
		})
	}
	for _, frozen := range []bool{false, true} {
		t.Run(map[bool]string{false: "duplicate", true: "frozen"}[frozen], func(t *testing.T) {
			app := New()
			app.Commands(func(c *Commands) { c.Register("count", "description", handler) })
			if frozen {
				_ = app.Execute(context.Background(), []string{"version"}, nil, io.Discard, io.Discard)
			}
			defer func() {
				if recover() == nil {
					t.Fatal("accepted duplicate or late registration")
				}
			}()
			app.Commands(func(c *Commands) { c.Register("count", "description", handler) })
		})
	}
}

func TestCommandHelpDoesNotOpenDatabase(t *testing.T) {
	app := New()
	app.Directory = t.TempDir()
	app.Commands(func(c *Commands) {
		c.Register("zebra", "last", func(*CommandContext) error { t.Fatal("help ran handler"); return nil })
		c.Register("alpha_count", "first", func(*CommandContext) error { return nil })
	})
	var output bytes.Buffer
	for _, args := range [][]string{{"help"}, {"help", "zebra"}, {"zebra", "--help"}, {"version"}} {
		if err := app.Execute(context.Background(), args, nil, &output, io.Discard); err != nil {
			t.Fatal(err)
		}
	}
	if strings.Index(output.String(), "alpha") > strings.Index(output.String(), "zebra") {
		t.Fatal(output.String())
	}
	if err := app.Execute(context.Background(), []string{"missing"}, nil, io.Discard, io.Discard); err == nil {
		t.Fatal("unknown command accepted")
	}
	entries, err := os.ReadDir(app.Directory)
	if err != nil || len(entries) != 0 {
		t.Fatalf("command created files: %v %v", entries, err)
	}
}

func TestCustomCommandContextAndErrors(t *testing.T) {
	app := New()
	app.Directory = t.TempDir()
	app.Database(func(environment string) (DatabaseConfig, error) {
		return DatabaseConfig{Driver: "sqlite", Database: "database/production.sqlite3"}, nil
	})
	var expectedError = errors.New("handler failed")
	var output bytes.Buffer
	var errorOutput bytes.Buffer
	var input = strings.NewReader("stdin")
	var ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	app.Commands(func(c *Commands) {
		c.Register("inspect", "Inspect context", func(command *CommandContext) error {
			if command.Environment != "production" || command.Context != ctx || command.DB.Statement.Context != ctx {
				t.Fatal("wrong environment or database context")
			}
			if !reflect.DeepEqual(command.Args, []string{"--name", "value", "--", "literal"}) {
				t.Fatal(command.Args)
			}
			data, err := io.ReadAll(command.In)
			if err != nil || string(data) != "stdin" {
				t.Fatal("wrong input")
			}
			_, _ = io.WriteString(command.Out, "out")
			_, _ = io.WriteString(command.Err, "err")
			cancel()
			if err := command.DB.Exec("SELECT 1").Error; !errors.Is(err, context.Canceled) {
				t.Fatalf("query cancellation: %v", err)
			}
			return expectedError
		})
	})
	err := app.Execute(ctx, []string{"inspect", "--name", "value", "--", "literal"}, input, &output, &errorOutput)
	if !errors.Is(err, expectedError) || output.String() != "out" || errorOutput.String() != "err" {
		t.Fatalf("%v %s %s", err, &output, &errorOutput)
	}
	if _, err := os.Stat(filepath.Join(app.Directory, "database/production.sqlite3")); err != nil {
		t.Fatal(err)
	}
}
