package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Exercise argument handling through the same entry point as the installed CLI.
// Buffers implement io.Writer, allowing output assertions without global stdout.
func TestNewCommand(t *testing.T) {
	var directory string = filepath.Join(t.TempDir(), "myapp")
	var output bytes.Buffer
	var errors bytes.Buffer
	var code int = run([]string{"new", "--module", "example.com/custom", directory}, &output, &errors)
	if code != 0 {
		t.Fatalf("code = %d: %s", code, errors.String())
	}
	var data []byte
	var err error
	data, err = os.ReadFile(filepath.Join(directory, "go.mod"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "module example.com/custom\n") {
		t.Fatalf("incorrect module: %s", data)
	}
	if !strings.Contains(output.String(), "bingo serve") {
		t.Fatal("missing next step")
	}
	output.Reset()
	errors.Reset()
	code = run([]string{"new", directory}, &output, &errors)
	if code != 1 || !strings.Contains(errors.String(), "refusing to overwrite") {
		t.Fatalf("repeat new: %d %s", code, errors.String())
	}
}

func TestNewCurrentDirectory(t *testing.T) {
	var directory string = t.TempDir()
	t.Chdir(directory)
	var output bytes.Buffer
	var errors bytes.Buffer
	if code := run([]string{"new", "."}, &output, &errors); code != 0 {
		t.Fatalf("code = %d: %s", code, errors.String())
	}
	if _, err := os.Stat("main.go"); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	expected := "module example.com/" + strings.ToLower(filepath.Base(directory)) + "\n"
	if !strings.Contains(string(contents), expected) {
		t.Fatalf("current folder module: %s", contents)
	}
}

func TestUsage(t *testing.T) {
	for _, arguments := range [][]string{nil, {"new"}, {"init"}, {"unknown"}, {"new", "one", "two"}, {"new", "--unknown"}} {
		var output bytes.Buffer
		var errors bytes.Buffer
		if code := run(arguments, &output, &errors); code != 2 {
			t.Fatalf("%v: code = %d", arguments, code)
		}
	}
	var output bytes.Buffer
	var errors bytes.Buffer
	if code := run([]string{"--help"}, &output, &errors); code != 0 {
		t.Fatalf("help: %d", code)
	}
}

func TestDefaultCommands(t *testing.T) {
	var app string = filepath.Join(t.TempDir(), "app")
	var output bytes.Buffer
	var errors bytes.Buffer
	if code := run([]string{"new", app}, &output, &errors); code != 0 {
		t.Fatal(errors.String())
	}
	var commands = [][]string{
		{"generate", "controller", "--app", app, "Reports"},
		{"generate", "model", "--app", app, "Task", "name:string", "completed:bool"},
		{"generate", "migration", "--app", app, "add_priority_to_tasks", "priority:integer"},
		{"db", "status", "--app", app, "--env", "test"},
		{"db", "migrate", "--app", app, "--env", "test"},
		{"db", "version", "--app", app, "--env", "test"},
		{"db", "rollback", "--app", app, "--env", "test"},
		{"version"}, {"help", "build"}, {"generate", "--help"}, {"db", "--help"},
	}
	for _, command := range commands {
		output.Reset()
		errors.Reset()
		if code := run(command, &output, &errors); code != 0 {
			t.Fatalf("%v: %d %s", command, code, errors.String())
		}
	}
	output.Reset()
	errors.Reset()
	if code := run([]string{"serve", "--production"}, &output, &errors); code != 2 {
		t.Fatalf("accepted production serve: %d", code)
	}
}

func TestCustomCommandDelegation(t *testing.T) {
	app := filepath.Join(t.TempDir(), "app")
	var output bytes.Buffer
	var errors bytes.Buffer
	if code := run([]string{"new", app}, &output, &errors); code != 0 {
		t.Fatal(errors.String())
	}
	source := `package config
import (
 "fmt"
 "github.com/hir4k/bingo"
)
func RegisterCommands(registry *bingo.Commands) {
 registry.Register("todo_count","Example test command",func(c *bingo.CommandContext) error {
  if len(c.Args)!=0 {return fmt.Errorf("usage: todo_count")}
  _,err:=fmt.Fprintln(c.Out,2)
  return err
 })
}
`
	if err := os.WriteFile(filepath.Join(app, "config/commands.go"), []byte(source), 0644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"help", "todo_count", "--app", app}, {"db", "migrate", "--app", app}, {"todo_count", "--app", app}} {
		output.Reset()
		errors.Reset()
		if code := run(args, &output, &errors); code != 0 {
			t.Fatalf("%v: %d %s", args, code, errors.String())
		}
	}
	if strings.TrimSpace(output.String()) != "2" {
		t.Fatal(output.String())
	}
	for _, args := range [][]string{{"todo_count", "--app", app, "unexpected"}, {"missing", "--app", app}} {
		output.Reset()
		errors.Reset()
		if code := run(args, &output, &errors); code != 1 {
			t.Fatalf("%v: %d %s", args, code, errors.String())
		}
	}
	if _, err := os.Stat(filepath.Join(app, "database/production.sqlite3")); !os.IsNotExist(err) {
		t.Fatal("development command opened production database")
	}
}
