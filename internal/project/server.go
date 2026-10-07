package project

import (
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"time"
)

// Build sets the runtime mode through the linker. Production assets are embedded
// by generated main.go; builds never migrate a database or start a server.
func Build(ctx context.Context, root string, destination string, development bool, output io.Writer, errorOutput io.Writer) error {
	var mode string = "production"
	if development {
		mode = "development"
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0755); err != nil {
		return err
	}
	var command *exec.Cmd = exec.CommandContext(ctx, "go", "build", "-mod=mod", "-ldflags=-X github.com/hir4k/bingo.BuildMode="+mode, "-o", destination, ".")
	command.Dir = root
	command.Env = append(os.Environ(), "GOWORK=off")
	command.Stdout = output
	command.Stderr = errorOutput
	return command.Run()
}

func sourceSnapshot(root string) (map[string][32]byte, error) {
	var files map[string][32]byte = make(map[string][32]byte)
	var err error = filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkError error) error {
		if walkError != nil {
			return walkError
		}
		if entry.IsDir() {
			if entry.Name() == ".git" || entry.Name() == "bin" || entry.Name() == "vendor" {
				return filepath.SkipDir
			}
			return nil
		}
		var name string = entry.Name()
		var watched bool = strings.HasSuffix(name, ".go") || name == "go.mod" || name == "go.sum"
		if !watched {
			return nil
		}
		var data []byte
		var err error
		data, err = os.ReadFile(path)
		if err != nil {
			return err
		}
		files[path] = sha256.Sum256(data)
		return nil
	})
	return files, err
}

func stopChild(child *exec.Cmd, done <-chan error) {
	_ = child.Process.Signal(os.Interrupt)
	select {
	case <-done:
	case <-time.After(12 * time.Second):
		_ = child.Process.Kill()
		<-done
	}
}

// Serve watches source/config files. Failed rebuilds preserve the running server;
// templates are read directly from disk in development. Temporary executables
// live outside the project, so the watcher cannot trigger itself on build output.
func Serve(ctx context.Context, root string, address string, output io.Writer, errorOutput io.Writer) error {
	var directory string
	var err error
	directory, err = os.MkdirTemp("", "bingo-serve-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(directory)
	var generation int
	var compile = func() (string, error) {
		generation++
		var binary string = filepath.Join(directory, fmt.Sprintf("app-%d", generation))
		if err := Build(ctx, root, binary, true, output, errorOutput); err != nil {
			return "", err
		}
		return binary, nil
	}
	var binary string
	binary, err = compile()
	if err != nil {
		return err
	}
	var start = func(path string) (*exec.Cmd, chan error, error) {
		var child *exec.Cmd = exec.Command(path)
		child.Dir = root
		child.Env = append(os.Environ(), "BINGO_APP_DIR="+root, "BINGO_ADDR="+address)
		child.Stdout = output
		child.Stderr = errorOutput
		if err := child.Start(); err != nil {
			return nil, nil, err
		}
		var done chan error = make(chan error, 1)
		go func() { done <- child.Wait() }()
		return child, done, nil
	}
	var child *exec.Cmd
	var done chan error
	child, done, err = start(binary)
	if err != nil {
		return err
	}
	var snapshot map[string][32]byte
	snapshot, err = sourceSnapshot(root)
	if err != nil {
		stopChild(child, done)
		return err
	}
	var ticker *time.Ticker = time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			stopChild(child, done)
			return nil
		case err = <-done:
			return fmt.Errorf("development server exited: %v", err)
		case <-ticker.C:
			var next map[string][32]byte
			next, err = sourceSnapshot(root)
			if err != nil {
				fmt.Fprintln(errorOutput, err)
				continue
			}
			if reflect.DeepEqual(snapshot, next) {
				continue
			}
			snapshot = next
			fmt.Fprintln(output, "Source changed; rebuilding.")
			var replacement string
			replacement, err = compile()
			if err != nil {
				fmt.Fprintln(errorOutput, "Rebuild failed; keeping the running server.")
				continue
			}
			stopChild(child, done)
			child, done, err = start(replacement)
			if err != nil {
				return err
			}
		}
	}
}
