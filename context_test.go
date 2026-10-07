package bingo

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// These cases verify observable responses, including escaping and atomic error
// handling. interface{} accepts a struct, map, or slice; templates resolve their
// fields at runtime. A pointer recorder implements the ResponseWriter interface.
func TestRender(t *testing.T) {
	var cases = []struct {
		name        string
		format      string
		source      string
		data        interface{}
		status      int
		contentType string
		expected    string
	}{
		{"html", "html", "<p>{{.Name}}</p>", struct{ Name string }{Name: "<script>"}, 200, "text/html; charset=utf-8", "<p>&lt;script&gt;</p>"},
		{"default", "", "{{.}}", "hello", 200, "text/html; charset=utf-8", "hello"},
		{"json", "json", "{{json .}}", "quote\"\n", 200, "application/json; charset=utf-8", "\"quote\\\"\\n\""},
		{"execution failure", "html", "partial{{.Missing}}", struct{ Name string }{}, 500, "", ""},
		{"parse failure", "html", "{{if}}", nil, 500, "", ""},
		{"invalid json", "json", "partial", nil, 500, "", ""},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var directory string = t.TempDir()
			var extension string = testCase.format
			if extension == "" {
				extension = "html"
			}
			var err error = os.WriteFile(filepath.Join(directory, "index."+extension+".ego"), []byte(testCase.source), 0600)
			if err != nil {
				t.Fatal(err)
			}
			var response *httptest.ResponseRecorder = httptest.NewRecorder()
			var controller Context = Context{ResponseWriter: response, Format: testCase.format, ViewsDir: directory}
			if err := controller.Render("index", testCase.data); err != nil {
				controller.writeError(err)
			}
			if response.Code != testCase.status {
				t.Fatalf("status = %d", response.Code)
			}
			if testCase.status == 500 {
				if strings.Contains(response.Body.String(), "partial") {
					t.Fatal("partial template response leaked")
				}
				return
			}
			if response.Header().Get("Content-Type") != testCase.contentType {
				t.Fatal("incorrect content type")
			}
			if response.Body.String() != testCase.expected {
				t.Fatalf("body = %q, want %q", response.Body.String(), testCase.expected)
			}
			if extension == "json" && !json.Valid(response.Body.Bytes()) {
				t.Fatal("invalid JSON response")
			}
		})
	}
}

// Missing files and traversal are separate from parsing failures: both must be
// rejected before any successful response header is committed to the writer.
func TestRenderMissingAndUnsafeViews(t *testing.T) {
	for _, path := range []string{"missing", "../outside"} {
		var response *httptest.ResponseRecorder = httptest.NewRecorder()
		var controller Context = Context{ResponseWriter: response, ViewsDir: t.TempDir()}
		if err := controller.Render(path, nil); err != nil {
			controller.writeError(err)
		}
		if response.Code != 500 {
			t.Fatalf("%s: status = %d", path, response.Code)
		}
	}
}
