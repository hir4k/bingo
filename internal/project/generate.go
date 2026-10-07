package project

import (
	"fmt"
	"go/format"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"gorm.io/gorm/schema"
)

var identifierPattern = regexp.MustCompile(`^[A-Z][A-Za-z0-9]*$`)
var snakePattern = regexp.MustCompile(`^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)*$`)

type field struct{ name, goName, goType, sqlType string }

func fields(arguments []string) ([]field, error) {
	var result []field
	var seen map[string]bool = map[string]bool{"id": true, "created_at": true, "updated_at": true}
	for _, argument := range arguments {
		var parts []string = strings.Split(argument, ":")
		if len(parts) != 2 || !snakePattern.MatchString(parts[0]) || seen[parts[0]] {
			return nil, fmt.Errorf("invalid or duplicate field %q; use name:type", argument)
		}
		seen[parts[0]] = true
		var goName string
		for _, word := range strings.Split(parts[0], "_") {
			goName += strings.ToUpper(word[:1]) + word[1:]
		}
		var goType, sqlType string
		switch parts[1] {
		case "string", "text":
			goType = "string"
			sqlType = "TEXT"
		case "bool", "boolean":
			goType = "bool"
			sqlType = "BOOLEAN"
		case "integer", "int":
			goType = "int64"
			sqlType = "INTEGER"
		case "float":
			goType = "float64"
			sqlType = "REAL"
		case "datetime":
			goType = "time.Time"
			sqlType = "DATETIME"
		default:
			return nil, fmt.Errorf("unsupported field type %q", parts[1])
		}
		result = append(result, field{name: parts[0], goName: goName, goType: goType, sqlType: sqlType})
	}
	return result, nil
}

// writeNewFiles preflights every collision and uses exclusive creation. If any
// write fails, only this operation's new files are removed; user files survive.
func writeNewFiles(root string, files map[string][]byte) (resultError error) {
	for name := range files {
		_, err := os.Lstat(filepath.Join(root, name))
		if err == nil {
			return fmt.Errorf("refusing to overwrite %s", name)
		}
		if !os.IsNotExist(err) {
			return err
		}
	}
	var created []string
	defer func() {
		if resultError != nil {
			for _, name := range created {
				_ = os.Remove(name)
			}
		}
	}()
	for name, data := range files {
		var path string = filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return err
		}
		var file *os.File
		var err error
		file, err = os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
		if err != nil {
			return err
		}
		created = append(created, path)
		_, err = file.Write(data)
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

// Sequential versions remain stable under fast consecutive generation, unlike
// second-resolution timestamps. Exclusive writes prevent concurrent overwrites.
func migrationFilename(root string, name string) (string, error) {
	if !snakePattern.MatchString(name) {
		return "", fmt.Errorf("migration names must be lowercase snake_case")
	}
	var matches []string
	var err error
	matches, err = filepath.Glob(filepath.Join(root, "database/migrations/*.sql"))
	if err != nil {
		return "", err
	}
	var highest int64
	for _, match := range matches {
		var version string = strings.SplitN(filepath.Base(match), "_", 2)[0]
		var number int64
		number, err = strconv.ParseInt(version, 10, 64)
		if err != nil || number <= 0 {
			return "", fmt.Errorf("invalid migration filename %s", match)
		}
		if number > highest {
			highest = number
		}
		if strings.HasSuffix(match, "_"+name+".sql") {
			return "", fmt.Errorf("migration %s already exists", name)
		}
	}
	if highest == int64(^uint64(0)>>1) {
		return "", fmt.Errorf("migration version overflow")
	}
	return fmt.Sprintf("database/migrations/%06d_%s.sql", highest+1, name), nil
}

func createTable(table string, columns []field) string {
	var sql strings.Builder
	fmt.Fprintf(&sql, "-- +goose Up\nCREATE TABLE %q (\n    id INTEGER PRIMARY KEY AUTOINCREMENT", table)
	for _, column := range columns {
		fmt.Fprintf(&sql, ",\n    %q %s", column.name, column.sqlType)
	}
	sql.WriteString(",\n    created_at DATETIME,\n    updated_at DATETIME\n);\n\n-- +goose Down\n")
	fmt.Fprintf(&sql, "DROP TABLE %q;\n", table)
	return sql.String()
}

func GenerateModel(root string, name string, arguments []string) error {
	release, lockError := generationLock(root)
	if lockError != nil {
		return lockError
	}
	defer release()

	if !identifierPattern.MatchString(name) || token.Lookup(name).IsKeyword() {
		return fmt.Errorf("model name must be an exported Go identifier")
	}
	var columns []field
	var err error
	columns, err = fields(arguments)
	if err != nil {
		return err
	}
	var naming schema.NamingStrategy
	var table string = naming.TableName(name)
	var filename string
	filename, err = migrationFilename(root, "create_"+table)
	if err != nil {
		return err
	}
	var code strings.Builder
	code.WriteString("// Models are plain structs; Goose migrations own schema changes.\npackage models\n\nimport \"time\"\n\n")
	fmt.Fprintf(&code, "type %s struct {\n ID uint `gorm:\"primaryKey\" json:\"id\"`\n", name)
	for _, column := range columns {
		fmt.Fprintf(&code, " %s %s `gorm:\"column:%s\" json:\"%s\"`\n", column.goName, column.goType, column.name, column.name)
	}
	code.WriteString(" CreatedAt time.Time `json:\"created_at\"`\n UpdatedAt time.Time `json:\"updated_at\"`\n}\n")
	var formatted []byte
	formatted, err = format.Source([]byte(code.String()))
	if err != nil {
		return err
	}
	return writeNewFiles(root, map[string][]byte{"models/" + naming.ColumnName("", name) + ".go": formatted, filename: []byte(createTable(table, columns))})
}

// Only create_TABLE and add_COLUMNS_to_TABLE are inferred. Other names produce
// a marked skeleton, never guessed SQL. Developers review generated migrations.
func GenerateMigration(root string, name string, arguments []string) (bool, error) {
	release, lockError := generationLock(root)
	if lockError != nil {
		return false, lockError
	}
	defer release()

	var filename string
	var err error
	filename, err = migrationFilename(root, name)
	if err != nil {
		return false, err
	}
	var columns []field
	columns, err = fields(arguments)
	if err != nil {
		return false, err
	}
	var sql string
	var inferred bool
	if strings.HasPrefix(name, "create_") && len(columns) > 0 {
		var table string = strings.TrimPrefix(name, "create_")
		if !snakePattern.MatchString(table) {
			return false, fmt.Errorf("invalid table name")
		}
		sql = createTable(table, columns)
		inferred = true
	} else if strings.HasPrefix(name, "add_") && strings.Contains(name, "_to_") && len(columns) > 0 {
		var pieces []string = strings.SplitN(strings.TrimPrefix(name, "add_"), "_to_", 2)
		var table string = pieces[1]
		var names []string
		for _, column := range columns {
			names = append(names, column.name)
		}
		if !snakePattern.MatchString(table) || pieces[0] != strings.Join(names, "_and_") {
			return false, fmt.Errorf("add migration name must match its declared columns")
		}
		sql = "-- +goose Up\n"
		for _, column := range columns {
			sql += fmt.Sprintf("ALTER TABLE %q ADD COLUMN %q %s;\n", table, column.name, column.sqlType)
		}
		sql += "\n-- +goose Down\n"
		for index := len(columns) - 1; index >= 0; index-- {
			sql += fmt.Sprintf("ALTER TABLE %q DROP COLUMN %q;\n", table, columns[index].name)
		}
		inferred = true
	} else {
		if len(columns) > 0 {
			return false, fmt.Errorf("field arguments require a supported create_ or add_ migration pattern")
		}
		// A deliberately invalid statement prevents an unfinished skeleton from being
		// marked applied by Goose. It must be replaced with reviewed SQL first.
		sql = "-- +goose Up\n-- Replace this guard with reviewed SQL.\nSELECT bingo_migration_requires_sql();\n\n-- +goose Down\nSELECT bingo_migration_requires_sql();\n"
	}
	err = writeNewFiles(root, map[string][]byte{filename: []byte(sql)})
	return inferred, err
}

func GenerateController(root string, name string) error {
	release, lockError := generationLock(root)
	if lockError != nil {
		return lockError
	}
	defer release()

	name = strings.TrimSuffix(name, "Controller")
	if !identifierPattern.MatchString(name) {
		return fmt.Errorf("controller name must be an exported Go identifier")
	}
	var naming schema.NamingStrategy
	var resource string = naming.ColumnName("", name)
	var source string = fmt.Sprintf(`package controllers
import "github.com/hir4k/bingo"
func %[1]sIndex(c *bingo.Context) error { return c.Render("%[2]s/index", []string{}) }
func %[1]sShow(c *bingo.Context) error { return bingo.HTTPError(404,"Record not found") }
`, name, resource)
	var formatted []byte
	var err error
	formatted, err = format.Source([]byte(source))
	if err != nil {
		return err
	}
	var files map[string][]byte = map[string][]byte{"controllers/" + resource + "_controller.go": formatted}
	for _, action := range []string{"index", "show"} {
		files["views/"+resource+"/"+action+".html.ego"] = []byte("<!doctype html>\n<html><head><title>" + name + "</title></head><body><pre>{{printf \"%v\" .}}</pre></body></html>\n")
		files["views/"+resource+"/"+action+".json.ego"] = []byte("{{json .}}\n")
	}
	return writeNewFiles(root, files)
}

// Version allocation and file writes must be one operation across CLI processes.
// A short-lived exclusive file prevents two generators choosing the same version.
func generationLock(root string) (func(), error) {
	var path string = filepath.Join(root, ".bingo-generation.lock")
	var file *os.File
	var err error
	file, err = os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, fmt.Errorf("cannot acquire generator lock %s: %w; retry when generation finishes", path, err)
	}
	if err = file.Close(); err != nil {
		_ = os.Remove(path)
		return nil, err
	}
	return func() { _ = os.Remove(path) }, nil
}
