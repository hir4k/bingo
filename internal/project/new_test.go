package project

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func frameworkRoot(t *testing.T) string {
	t.Helper()
	var root string
	var err error
	root, err = filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	return root
}

// Build and exercise the generated application against the real framework.
// Working templates, local imports, and workspace settings are observable here;
// assertions do not merely duplicate the embedded file contents.
func TestNewCreatesEmptyRunnableProject(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "myapp")
	if err := New(directory, "example.com/myapp", frameworkRoot(t)); err != nil {
		t.Fatal(err)
	}
	for _, filename := range []string{"main.go", "config/routes.go", "config/commands.go", "config/jobs.go", "config/mcp.go", "config/database.go", "go.mod", "go.work", "README.md", "AGENTS.md", ".gitignore", "database/migrations/000001_create_bingo_jobs.sql"} {
		if _, err := os.Stat(filepath.Join(directory, filename)); err != nil {
			t.Fatalf("missing %s: %v", filename, err)
		}
	}
	for _, folder := range []string{"controllers", "models", "commands", "jobs", "mcp", "views"} {
		entries, err := os.ReadDir(filepath.Join(directory, folder))
		if err != nil || len(entries) != 1 || entries[0].Name() != ".keep" {
			t.Fatalf("expected empty %s with .keep: %v %v", folder, entries, err)
		}
	}
	sources, err := filepath.Glob(filepath.Join(directory, "*.go"))
	if err != nil || len(sources) != 1 || filepath.Base(sources[0]) != "main.go" {
		t.Fatalf("root sources: %v %v", sources, err)
	}
	integration := `package main
import (
 "context"
 "bytes"
 "io/fs"
 "net/http/httptest"
 "strings"
 "testing"
 "github.com/hir4k/bingo"
 "example.com/myapp/config"
)
func TestEmptyApplication(t *testing.T) {
 app:=bingo.New()
 app.Views(assets)
 app.Database(config.Database)
 app.Routes(config.RegisterRoutes)
 app.Commands(config.RegisterCommands)
 app.Jobs(config.RegisterJobs)
 for _, path:=range []string{"views/.keep","database/migrations/000001_create_bingo_jobs.sql"} {
  if _,err:=fs.Stat(assets,path);err!=nil {t.Fatal(err)}
 }
 handler:=app.Handler()
 for _,path:=range []string{"/todos","/mcp"} {
  response:=httptest.NewRecorder()
  handler.ServeHTTP(response,httptest.NewRequest("GET",path,nil))
  if response.Code!=404 {t.Fatalf("unexpected default route %s: %d",path,response.Code)}
 }
 var output bytes.Buffer
 if err:=app.Execute(context.Background(),[]string{"help"},nil,&output,&output);err!=nil {t.Fatal(err)}
 if strings.Contains(output.String(),"todo_count") {t.Fatal("default custom command registered")}
}
`
	if err := os.WriteFile(filepath.Join(directory, "generated_test.go"), []byte(integration), 0644); err != nil {
		t.Fatal(err)
	}
	for _, workspace := range []string{"off", "auto"} {
		command := exec.Command("go", "test", "./...")
		command.Dir = directory
		command.Env = append(os.Environ(), "GOWORK="+workspace)
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("generated app with GOWORK=%s: %v\n%s", workspace, err, output)
		}
	}
	var output bytes.Buffer
	if err := Migrate(context.Background(), directory, "test", "migrate", &output); err != nil {
		t.Fatal(err)
	}
}

func TestNewPreservesNonemptyDirectory(t *testing.T) {
	var directory string = t.TempDir()
	var path string = filepath.Join(directory, "main.go")
	var original []byte = []byte("existing user code\n")
	if err := os.WriteFile(path, original, 0644); err != nil {
		t.Fatal(err)
	}
	if err := New(directory, "example.com/myapp", frameworkRoot(t)); err == nil {
		t.Fatal("accepted nonempty directory")
	}
	var data []byte
	var err error
	data, err = os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(data, original) {
		t.Fatal("changed existing file")
	}
	var entries []os.DirEntry
	entries, err = os.ReadDir(directory)
	if err != nil || len(entries) != 1 {
		t.Fatalf("partial scaffold created: %v, %v", entries, err)
	}
}

func TestNewSupportsExistingEmptyDirectory(t *testing.T) {
	var directory string = t.TempDir()
	if err := New(directory, "example.com/myapp", frameworkRoot(t)); err != nil {
		t.Fatal(err)
	}
	if err := New(directory, "example.com/myapp", frameworkRoot(t)); err == nil {
		t.Fatal("accepted a second initialization")
	}
}

func TestNewRejectsInvalidOptionsBeforeWriting(t *testing.T) {
	var parent string = t.TempDir()
	for _, module := range []string{"", "bad module", "foo\nbar", "../app", "example.com//app", "github.com/hir4k/bingo"} {
		var directory string = filepath.Join(parent, "app")
		if err := New(directory, module, frameworkRoot(t)); err == nil {
			t.Fatalf("accepted module %q", module)
		}
		if _, err := os.Stat(directory); !os.IsNotExist(err) {
			t.Fatalf("created directory for invalid module %q", module)
		}
	}
	var directory string = filepath.Join(parent, "app")
	if err := New(directory, "example.com/app", parent); err == nil {
		t.Fatal("accepted an invalid framework checkout")
	}
	if _, err := os.Stat(directory); !os.IsNotExist(err) {
		t.Fatal("created directory for invalid framework checkout")
	}
}
