package project

import (
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
)

// RunCommand compiles the application in development mode and forwards its
// arguments unchanged. Custom commands use the same binary dispatcher as db.
func RunCommand(ctx context.Context, root string, args []string, input io.Reader, output io.Writer, errorOutput io.Writer) error {
	var directory string
	var err error
	directory, err = os.MkdirTemp("", "bingo-command-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(directory)
	var binary string = filepath.Join(directory, "app")
	if err = Build(ctx, root, binary, true, output, errorOutput); err != nil {
		return err
	}
	var child *exec.Cmd = exec.Command(binary, args...)
	child.Dir = root
	child.Env = append(os.Environ(), "BINGO_APP_DIR="+root)
	child.Stdin = input
	child.Stdout = output
	child.Stderr = errorOutput
	if err = child.Start(); err != nil {
		return err
	}
	var done chan error = make(chan error, 1)
	go func() { done <- child.Wait() }()
	select {
	case err = <-done:
		return err
	case <-ctx.Done():
		stopChild(child, done)
		return ctx.Err()
	}
}
