package project

import (
	"bytes"
	"context"
	"github.com/hir4k/bingo"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// Both child process streams can write concurrently. Keep test output safe for
// the race detector and for polling during rebuilds.
type lockedBuffer struct {
	mutex  sync.Mutex
	buffer bytes.Buffer
}

func (b *lockedBuffer) Write(data []byte) (int, error) {
	b.mutex.Lock()
	defer b.mutex.Unlock()
	return b.buffer.Write(data)
}
func (b *lockedBuffer) String() string {
	b.mutex.Lock()
	defer b.mutex.Unlock()
	return b.buffer.String()
}

func availableAddress(t *testing.T) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	var address string = listener.Addr().String()
	_ = listener.Close()
	return address
}

func waitHTTP(t *testing.T, address string, predicate func(*http.Response, string) bool) {
	t.Helper()
	var deadline time.Time = time.Now().Add(20 * time.Second)
	var client http.Client = http.Client{Timeout: time.Second}
	for time.Now().Before(deadline) {
		response, err := client.Get("http://" + address + "/todos.json")
		if err == nil {
			data, _ := io.ReadAll(response.Body)
			_ = response.Body.Close()
			if predicate(response, string(data)) {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("server did not reach expected state")
}

func TestProductionBuildIsStandalone(t *testing.T) {
	var root string = newTodoProject(t)
	var output lockedBuffer
	var binary string = filepath.Join(root, "bin/app")
	t.Setenv("BINGO_PRODUCTION_DATABASE", "database/build-time.sqlite3")
	if err := Build(context.Background(), root, binary, false, &output, &output); err != nil {
		t.Fatalf("build: %v %s", err, output.String())
	}
	if _, err := os.Stat(filepath.Join(root, "database/production.sqlite3")); !os.IsNotExist(err) {
		t.Fatal("build created a database")
	}
	var deployed string = t.TempDir()
	t.Setenv("BINGO_PRODUCTION_DATABASE", "database/runtime.sqlite3")
	runCommand := func(args ...string) string {
		t.Helper()
		var child *exec.Cmd = exec.Command(binary, args...)
		child.Dir = deployed
		child.Env = append(os.Environ(), "PATH=", "BINGO_APP_DIR="+deployed)
		data, err := child.CombinedOutput()
		if err != nil {
			t.Fatalf("%v: %v %s", args, err, data)
		}
		return string(data)
	}
	if help := runCommand("help"); !strings.Contains(help, "todo_count") {
		t.Fatal(help)
	}
	runCommand("version")
	if _, err := os.Stat(filepath.Join(deployed, "database")); !os.IsNotExist(err) {
		t.Fatal("help or version opened a database")
	}
	runCommand("db", "migrate")
	if _, err := os.Stat(filepath.Join(deployed, "database/runtime.sqlite3")); err != nil {
		t.Fatal("runtime environment was not used", err)
	}
	if _, err := os.Stat(filepath.Join(deployed, "database/build-time.sqlite3")); !os.IsNotExist(err) {
		t.Fatal("build captured environment values")
	}
	if count := runCommand("todo_count"); strings.TrimSpace(count) != "2" {
		t.Fatalf("count: %s", count)
	}
	if status := runCommand("db", "status"); !strings.Contains(strings.ToLower(status), "applied") {
		t.Fatal(status)
	}
	runCommand("db", "version")
	runCommand("db", "rollback")
	runCommand("db", "migrate")
	var err error
	var address string = availableAddress(t)
	var child *exec.Cmd = exec.Command(binary)
	child.Dir = deployed
	child.Env = append(os.Environ(), "PATH=", "BINGO_APP_DIR="+deployed, "BINGO_ADDR="+address)
	child.Stdout = &output
	child.Stderr = &output
	if err = child.Start(); err != nil {
		t.Fatal(err)
	}
	var done chan error = make(chan error, 1)
	go func() { done <- child.Wait() }()
	defer stopChild(child, done)
	waitHTTP(t, address, func(response *http.Response, body string) bool {
		return response.StatusCode == 200 && strings.Contains(body, "Learn Go templates")
	})
	if !strings.Contains(output.String(), "(production)") {
		t.Fatal(output.String())
	}
	// There is no source tree, templates, config, Go, or Bingo CLI in deployment.
	if _, err = os.Stat(filepath.Join(deployed, "views")); !os.IsNotExist(err) {
		t.Fatal("test unexpectedly has disk templates")
	}
}

func TestServeReloadAndFailedBuild(t *testing.T) {
	var root string = newTodoProject(t)
	var output lockedBuffer
	if err := Migrate(context.Background(), root, "development", "migrate", &output); err != nil {
		t.Fatal(err)
	}
	if err := Migrate(context.Background(), root, "test", "migrate", &output); err != nil {
		t.Fatal(err)
	}
	settings := bingo.DatabaseConfig{Driver: "sqlite", Database: filepath.Join(root, "database/test.sqlite3")}
	db, err := bingo.OpenDatabase(settings)
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Exec("UPDATE todos SET name = ? WHERE id = 1", "Reloaded database config").Error; err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	_ = pool.Close()
	var ctx context.Context
	var cancel context.CancelFunc
	ctx, cancel = context.WithCancel(context.Background())
	var done chan error = make(chan error, 1)
	var address string = availableAddress(t)
	go func() { done <- Serve(ctx, root, address, &output, &output) }()
	defer func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(15 * time.Second):
			t.Error("development server did not stop")
		}
	}()
	waitHTTP(t, address, func(response *http.Response, body string) bool { return response.StatusCode == 200 })
	if !strings.Contains(output.String(), "(development)") {
		t.Fatal(output.String())
	}
	configPath := filepath.Join(root, "config/database.go")
	configSource, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatal(err)
	}
	configSource = bytes.ReplaceAll(configSource, []byte("database/development.sqlite3"), []byte("database/test.sqlite3"))
	if err := os.WriteFile(configPath, configSource, 0644); err != nil {
		t.Fatal(err)
	}
	waitHTTP(t, address, func(response *http.Response, body string) bool {
		return response.StatusCode == 200 && strings.Contains(body, "Reloaded database config")
	})
	var path string = filepath.Join(root, "controllers/todos_controller.go")
	var source []byte
	source, err = os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	source = bytes.Replace(source, []byte(`return c.Render("todos/index", todos)`), []byte(`c.ResponseWriter.Header().Set("X-Reload","yes");return c.Render("todos/index", todos)`), 1)
	if err = os.WriteFile(path, source, 0644); err != nil {
		t.Fatal(err)
	}
	waitHTTP(t, address, func(response *http.Response, body string) bool { return response.Header.Get("X-Reload") == "yes" })
	if err = os.WriteFile(filepath.Join(root, "broken.go"), []byte("this is not Go"), 0644); err != nil {
		t.Fatal(err)
	}
	var deadline time.Time = time.Now().Add(20 * time.Second)
	for !strings.Contains(output.String(), "Rebuild failed") && time.Now().Before(deadline) {
		time.Sleep(100 * time.Millisecond)
	}
	if !strings.Contains(output.String(), "Rebuild failed") {
		t.Fatal(output.String())
	}
	waitHTTP(t, address, func(response *http.Response, body string) bool {
		return response.StatusCode == 200 && response.Header.Get("X-Reload") == "yes"
	})
}

// Server lifecycle tests add an explicit demo fixture; new applications stay empty.
func newTodoProject(t *testing.T) string {
	t.Helper()
	root := newProject(t)
	if err := os.Remove(filepath.Join(root, "database/migrations/000001_create_bingo_jobs.sql")); err != nil {
		t.Fatal(err)
	}
	example := filepath.Join(frameworkRoot(t), "examples/todo")
	for _, folder := range []string{"config", "controllers", "models", "commands", "jobs", "views", "database/migrations"} {
		source := filepath.Join(example, folder)
		err := filepath.WalkDir(source, func(path string, entry os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			relative, err := filepath.Rel(example, path)
			if err != nil {
				return err
			}
			target := filepath.Join(root, relative)
			if entry.IsDir() {
				return os.MkdirAll(target, 0755)
			}
			contents, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			contents = bytes.ReplaceAll(contents, []byte("example.com/todo"), []byte("example.com/app"))
			return os.WriteFile(target, contents, 0644)
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	return root
}
