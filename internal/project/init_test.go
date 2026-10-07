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
func TestInitCreatesRunnableProject(t *testing.T) {
	var directory string = filepath.Join(t.TempDir(), "myapp")
	var err error = Init(directory, "example.com/myapp", frameworkRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, filename := range []string{"main.go", "config/routes.go", "config/commands.go", "commands/commands.go", "controllers/todos_controller.go", "models/todo.go", "config/database.go", "database/migrations/000001_create_todos.sql", "go.mod", "go.work", "README.md", "AGENTS.md", ".gitignore", "views/todos/index.html.ego", "views/todos/index.json.ego", "views/todos/show.html.ego", "views/todos/show.json.ego"} {
		if _, err = os.Stat(filepath.Join(directory, filename)); err != nil {
			t.Fatalf("missing %s: %v", filename, err)
		}
	}
	rootSources, err := filepath.Glob(filepath.Join(directory, "*.go"))
	if err != nil || len(rootSources) != 1 || filepath.Base(rootSources[0]) != "main.go" {
		t.Fatalf("expected only main.go at project root: %v %v", rootSources, err)
	}
	var migrationOutput bytes.Buffer
	err = Migrate(context.Background(), directory, "test", "migrate", &migrationOutput)
	if err != nil {
		t.Fatal(err)
	}
	var integrationTest string = `package main
import (
 "encoding/json"
 "net/http/httptest"
 "strings"
 "testing"
 "github.com/hir4k/bingo"
 "example.com/myapp/config"
)
func TestGeneratedResponses(t *testing.T) {
 app := bingo.New()
 app.Views(assets)
 app.Database(config.Database)
 dbConfig, err := app.DatabaseSettings("test")
 if err != nil { t.Fatal(err) }
 app.DB,err=bingo.OpenDatabase(dbConfig)
 if err != nil { t.Fatal(err) }
 pool,_:=app.DB.DB();defer pool.Close()
 app.Routes(config.RegisterRoutes)
 handler := app.Handler()
 for _,path := range []string{"/todos","/todos.json","/todos/1","/todos/1.json"} {
  response := httptest.NewRecorder()
  handler.ServeHTTP(response,httptest.NewRequest("GET",path,nil))
  if response.Code != 200 { t.Fatalf("%s: %d %s",path,response.Code,response.Body.String()) }
  if strings.HasSuffix(path,".json") {
   if !json.Valid(response.Body.Bytes()) { t.Fatalf("invalid JSON response: %s",response.Body.String()) }
  } else if !strings.Contains(response.Body.String(),"Learn Go templates") { t.Fatal("model was not rendered") }
 }
 rootApp:=bingo.New()
 rootApp.DB=app.DB
 rootApp.Views(assets)
 rootApp.Routes(func(root *bingo.Router){root.Group("/api",func(api *bingo.Router){config.RegisterRoutes(api)})})
 grouped:=rootApp.Handler()
 response:=httptest.NewRecorder()
 grouped.ServeHTTP(response,httptest.NewRequest("GET","/api/todos",nil))
 if response.Code!=200||!strings.Contains(response.Body.String(),` + "`" + `href="/api/todos/1"` + "`" + `){t.Fatalf("group links: %s",response.Body.String())}
 request:=httptest.NewRequest("POST","/api/todos.json",strings.NewReader(` + "`" + `{"name":"Grouped","completed":false}` + "`" + `))
 request.Header.Set("Content-Type","application/json")
 response=httptest.NewRecorder()
 grouped.ServeHTTP(response,request)
 if response.Code!=303||!strings.HasPrefix(response.Header().Get("Location"),"/api/todos/"){t.Fatalf("group redirect: %d %s",response.Code,response.Header().Get("Location"))}
 location:=response.Header().Get("Location")
 request=httptest.NewRequest("PATCH",location,strings.NewReader(` + "`" + `{"name":"Updated","completed":false}` + "`" + `))
 request.Header.Set("Content-Type","application/json")
 response=httptest.NewRecorder();grouped.ServeHTTP(response,request)
 if response.Code!=303 {t.Fatalf("update: %d %s",response.Code,response.Body.String())}
 response=httptest.NewRecorder();grouped.ServeHTTP(response,httptest.NewRequest("GET",location,nil))
 if response.Code!=200||!strings.Contains(response.Body.String(),"Updated"){t.Fatalf("updated record: %d %s",response.Code,response.Body.String())}
 request=httptest.NewRequest("POST","/api/todos.json",strings.NewReader(` + "`" + `{"id":99,"name":"Rejected"}` + "`" + `))
 request.Header.Set("Content-Type","application/json")
 response=httptest.NewRecorder();grouped.ServeHTTP(response,request)
 if response.Code!=400 {t.Fatalf("unknown input field: %d %s",response.Code,response.Body.String())}
 response=httptest.NewRecorder();grouped.ServeHTTP(response,httptest.NewRequest("DELETE",location,nil))
 if response.Code!=204 {t.Fatalf("destroy: %d %s",response.Code,response.Body.String())}
 response=httptest.NewRecorder();grouped.ServeHTTP(response,httptest.NewRequest("GET",location,nil))
 if response.Code!=404 {t.Fatalf("deleted record: %d %s",response.Code,response.Body.String())}
}
`

	err = os.WriteFile(filepath.Join(directory, "generated_test.go"), []byte(integrationTest), 0644)
	if err != nil {
		t.Fatal(err)
	}
	for _, workspace := range []string{"off", "auto"} {
		var command *exec.Cmd = exec.Command("go", "test", "-mod=mod", "./...")
		if workspace == "auto" {
			command = exec.Command("go", "test", "./...")
		}
		command.Dir = directory
		command.Env = append(os.Environ(), "GOWORK="+workspace)
		var output []byte
		output, err = command.CombinedOutput()
		if err != nil {
			t.Fatalf("generated app failed with GOWORK=%s: %v\n%s", workspace, err, output)
		}
	}
}

func TestInitPreservesNonemptyDirectory(t *testing.T) {
	var directory string = t.TempDir()
	var path string = filepath.Join(directory, "main.go")
	var original []byte = []byte("existing user code\n")
	if err := os.WriteFile(path, original, 0644); err != nil {
		t.Fatal(err)
	}
	if err := Init(directory, "example.com/myapp", frameworkRoot(t)); err == nil {
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

func TestInitSupportsExistingEmptyDirectory(t *testing.T) {
	var directory string = t.TempDir()
	if err := Init(directory, "example.com/myapp", frameworkRoot(t)); err != nil {
		t.Fatal(err)
	}
	if err := Init(directory, "example.com/myapp", frameworkRoot(t)); err == nil {
		t.Fatal("accepted a second initialization")
	}
}

func TestInitRejectsInvalidOptionsBeforeWriting(t *testing.T) {
	var parent string = t.TempDir()
	for _, module := range []string{"", "bad module", "foo\nbar", "../app", "example.com//app", "github.com/hir4k/bingo"} {
		var directory string = filepath.Join(parent, "app")
		if err := Init(directory, module, frameworkRoot(t)); err == nil {
			t.Fatalf("accepted module %q", module)
		}
		if _, err := os.Stat(directory); !os.IsNotExist(err) {
			t.Fatalf("created directory for invalid module %q", module)
		}
	}
	var directory string = filepath.Join(parent, "app")
	if err := Init(directory, "example.com/app", parent); err == nil {
		t.Fatal("accepted an invalid framework checkout")
	}
	if _, err := os.Stat(directory); !os.IsNotExist(err) {
		t.Fatal("created directory for invalid framework checkout")
	}
}
