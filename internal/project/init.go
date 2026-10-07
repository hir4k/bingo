// Package project creates a small runnable app using embedded default files.
package project

import (
	"embed"
	"fmt"
	"go/format"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Embedding makes init work without locating template files at runtime.
//
//go:embed templates/*.txt templates/views/*.txt
var templates embed.FS

var modulePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._~/-]*$`)

// Init creates only an empty or new directory. modulePath names the app's Go
// module; frameworkDir identifies the local Bingo checkout. No network is used.
func Init(destination string, modulePath string, frameworkDir string) (resultError error) {
	var validModule bool = modulePattern.MatchString(modulePath) && !strings.HasSuffix(modulePath, "/") && !strings.Contains(modulePath, "//")
	if !validModule {
		return fmt.Errorf("invalid module path %q", modulePath)
	}
	for _, segment := range strings.Split(modulePath, "/") {
		if segment == "." || segment == ".." {
			return fmt.Errorf("invalid module path %q", modulePath)
		}
	}
	var target string
	var framework string
	var err error
	target, err = filepath.Abs(destination)
	if err != nil {
		return err
	}
	framework, err = filepath.Abs(frameworkDir)
	if err != nil {
		return err
	}
	var moduleFile []byte
	moduleFile, err = os.ReadFile(filepath.Join(framework, "go.mod"))
	if err != nil {
		return fmt.Errorf("cannot read Bingo checkout: %w", err)
	}
	var version string
	var frameworkModule string
	for _, line := range strings.Split(string(moduleFile), "\n") {
		var fields []string = strings.Fields(line)
		if len(fields) != 2 {
			continue
		}
		if fields[0] == "module" {
			frameworkModule = fields[1]
		}
		if fields[0] == "go" {
			version = fields[1]
		}
	}
	if frameworkModule != "github.com/hir4k/bingo" || version == "" {
		return fmt.Errorf("--framework must point to the Bingo module root")
	}
	if modulePath == frameworkModule {
		return fmt.Errorf("application module must differ from the framework module")
	}
	var info os.FileInfo
	info, err = os.Lstat(target)
	var newDirectory bool = os.IsNotExist(err)
	if err != nil && !newDirectory {
		return err
	}
	if !newDirectory {
		if !info.IsDir() {
			return fmt.Errorf("destination must be a directory")
		}
		var entries []os.DirEntry
		entries, err = os.ReadDir(target)
		if err != nil {
			return err
		}
		if len(entries) != 0 {
			return fmt.Errorf("destination is not empty; refusing to overwrite files: %s", target)
		}
	}
	var name string = filepath.Base(target)
	var replacements *strings.Replacer = strings.NewReplacer("__PROJECT_NAME__", name, "__BINARY_NAME__", filepath.Base(modulePath), "__MODULE__", modulePath)
	var files map[string][]byte = make(map[string][]byte)
	for filename, source := range map[string]string{
		"main.go":                                     "main.go.txt",
		"controllers/todos_controller.go":             "todo_controller.go.txt",
		"models/todo.go":                              "todo.go.txt",
		"config/commands.go":                          "commands.go.txt",
		"commands/commands.go":                        "custom_commands.go.txt",
		"config/routes.go":                            "routes.go.txt",
		"config/database.go":                          "database.go.txt",
		"database/migrations/000001_create_todos.sql": "migration.sql.txt",
		"README.md":                                   "README.md.txt",
		"AGENTS.md":                                   "AGENTS.md.txt",
		".gitignore":                                  "gitignore.txt",
	} {
		var contents []byte
		contents, err = templates.ReadFile("templates/" + source)
		if err != nil {
			return err
		}
		// User-provided directory names are substituted only in documentation and
		// ignore rules. Go sources and their template actions remain literal.
		contents = []byte(replacements.Replace(string(contents)))
		if strings.HasSuffix(filename, ".go") {
			contents, err = format.Source(contents)
			if err != nil {
				return err
			}
		}
		files[filename] = contents
	}
	var views []os.DirEntry
	views, err = templates.ReadDir("templates/views")
	if err != nil {
		return err
	}
	for _, view := range views {
		var contents []byte
		contents, err = templates.ReadFile("templates/views/" + view.Name())
		if err != nil {
			return err
		}
		files["views/todos/"+strings.TrimSuffix(view.Name(), ".txt")] = contents
	}
	var frameworkPath string = strconv.Quote(filepath.ToSlash(framework))
	files["go.mod"] = []byte("module " + modulePath + "\n\ngo " + version + "\n\nrequire github.com/hir4k/bingo v0.0.0\n\nreplace github.com/hir4k/bingo => " + frameworkPath + "\n")
	// Copy the framework dependency graph/checksums so generated apps can build
	// without immediately requiring go mod tidy just to resolve local imports.
	var dependencyStart int = strings.Index(string(moduleFile), "require ")
	if dependencyStart >= 0 {
		files["go.mod"] = append(files["go.mod"], []byte("\n"+string(moduleFile)[dependencyStart:])...)
	}
	var checksums []byte
	checksums, err = os.ReadFile(filepath.Join(framework, "go.sum"))
	if err != nil {
		return err
	}
	files["go.sum"] = checksums
	files["go.work"] = []byte("go " + version + "\n\nuse (\n\t.\n\t" + frameworkPath + "\n)\n")
	var names []string
	for filename := range files {
		names = append(names, filename)
	}
	sort.Strings(names)

	var createdFiles []string
	var createdDirectories []string
	// Only remove entries created by this call on failure. An existing empty
	// destination is preserved, and O_EXCL prevents overwriting a concurrent file.
	defer func() {
		if resultError == nil {
			return
		}
		for _, path := range createdFiles {
			_ = os.Remove(path)
		}
		for index := len(createdDirectories) - 1; index >= 0; index-- {
			_ = os.Remove(createdDirectories[index])
		}
	}()
	if newDirectory {
		err = os.MkdirAll(filepath.Dir(target), 0755)
		if err != nil {
			return err
		}
		err = os.Mkdir(target, 0755)
		if err != nil {
			return err
		}
		createdDirectories = append(createdDirectories, target)
	}
	for _, directory := range []string{"views", "views/todos", "controllers", "models", "commands", "config", "database", "database/migrations"} {
		var path string = filepath.Join(target, directory)
		err = os.Mkdir(path, 0755)
		if err != nil {
			return err
		}
		createdDirectories = append(createdDirectories, path)
	}
	for _, filename := range names {
		var path string = filepath.Join(target, filename)
		var file *os.File
		file, err = os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if err != nil {
			return err
		}
		createdFiles = append(createdFiles, path)
		_, err = file.Write(files[filename])
		var closeError error = file.Close()
		if err != nil {
			return err
		}
		if closeError != nil {
			return closeError
		}
	}
	return nil
}
