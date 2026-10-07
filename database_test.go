package bingo

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestDatabaseProviderResolvesRuntimeValues(t *testing.T) {
	app := New()
	app.Directory = t.TempDir()
	var environments []string
	app.Database(func(environment string) (DatabaseConfig, error) {
		environments = append(environments, environment)
		filename := os.Getenv("BINGO_TEST_PROVIDER_DATABASE")
		if filename == "" {
			filename = "database/" + environment + ".sqlite3"
		}
		return DatabaseConfig{Driver: "sqlite", Database: filename}, nil
	})
	config, err := app.DatabaseSettings("test")
	if err != nil || config.Database != filepath.Join(app.Directory, "database/test.sqlite3") {
		t.Fatalf("%v %v", config, err)
	}
	t.Setenv("BINGO_TEST_PROVIDER_DATABASE", filepath.Join(app.Directory, "quote\"\n.sqlite3"))
	config, err = app.DatabaseSettings("production")
	if err != nil || config.Database != os.Getenv("BINGO_TEST_PROVIDER_DATABASE") {
		t.Fatalf("runtime value: %v %v", config, err)
	}
	if len(environments) != 2 || environments[0] != "test" || environments[1] != "production" {
		t.Fatal(environments)
	}
}

func TestDatabaseProviderErrors(t *testing.T) {
	expected := errors.New("unknown environment")
	for _, scenario := range []string{"missing", "provider error", "unsupported driver", "empty path"} {
		t.Run(scenario, func(t *testing.T) {
			app := New()
			if scenario != "missing" {
				app.Database(func(environment string) (DatabaseConfig, error) {
					if scenario == "provider error" {
						return DatabaseConfig{}, expected
					}
					if scenario == "unsupported driver" {
						return DatabaseConfig{Driver: "postgres", Database: "x"}, nil
					}
					return DatabaseConfig{Driver: "sqlite"}, nil
				})
			}
			_, err := app.DatabaseSettings("unknown")
			if err == nil {
				t.Fatal("invalid config accepted")
			}
			if scenario == "provider error" && !errors.Is(err, expected) {
				t.Fatal(err)
			}
		})
	}
}

func TestDatabaseRegistrationRules(t *testing.T) {
	provider := func(string) (DatabaseConfig, error) {
		return DatabaseConfig{Driver: "sqlite", Database: "database/test.sqlite3"}, nil
	}
	for _, scenario := range []string{"nil", "duplicate", "after handler", "after command"} {
		t.Run(scenario, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Fatal("invalid registration accepted")
				}
			}()
			app := New()
			switch scenario {
			case "nil":
				app.Database(nil)
			case "duplicate":
				app.Database(provider)
				app.Database(provider)
			case "after handler":
				app.Handler()
				app.Database(provider)
			case "after command":
				_ = app.Execute(t.Context(), []string{"help"}, nil, io.Discard, io.Discard)
				app.Database(provider)
			}
		})
	}
}
