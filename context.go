// Package bingo provides a small MVC framework using Go standard-library templates.
package bingo

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"gorm.io/gorm"
	"html/template"
	"io"
	"io/fs"
	"log"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	texttemplate "text/template"
)

// Context contains one request's state and a native context-bound GORM session.

// Tracking committed bytes prevents an error after a write from appending a
// second response or exposing diagnostics in a partially sent document.
type responseState struct {
	http.ResponseWriter
	committed bool
}

func (w *responseState) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *responseState) WriteHeader(status int) {
	if w.committed {
		return
	}
	w.committed = true
	w.ResponseWriter.WriteHeader(status)
}
func (w *responseState) Write(data []byte) (int, error) {
	if !w.committed {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(data)
}

type Context struct {
	ResponseWriter http.ResponseWriter
	Request        *http.Request
	Format         string
	Params         map[string]string
	ViewsDir       string
	app            *App
	DB             *gorm.DB
	Views          fs.FS
	Development    bool
}

// Render evaluates a view into memory before committing response bytes. HTML is
// escaped contextually, and JSON is validated after template execution. data can
// be a model value or slice because interface{} accepts any Go value.
func (c *Context) Render(viewPath string, data interface{}) error {
	var format string = c.Format
	if format == "" {
		format = "html"
	}
	if format != "html" && format != "json" {
		return HTTPError(http.StatusNotAcceptable, "Unsupported response format")
	}

	// IsLocal rejects absolute paths and parent traversal. Join handles native
	// directory separators, but does not itself enforce containment or symlinks.
	// View names come from application code, not directly from URL parameters.
	if !filepath.IsLocal(viewPath) {
		return fmt.Errorf("invalid view path %q", viewPath)
	}
	var viewsDir string = c.ViewsDir
	if viewsDir == "" {
		viewsDir = "views"
	}
	var templatePath string = filepath.Join(viewsDir, viewPath+"."+format+".ego")
	var source []byte
	var err error
	if c.Views != nil && !c.Development {
		source, err = fs.ReadFile(c.Views, "views/"+viewPath+"."+format+".ego")
	} else {
		source, err = os.ReadFile(templatePath)
	}
	if err != nil {
		return err
	}

	var buffer bytes.Buffer
	if format == "html" {
		// html/template escapes data according to its HTML context. &buffer
		// passes a pointer implementing io.Writer, so Execute can append bytes.
		var view *template.Template
		view, err = template.New(filepath.Base(templatePath)).Funcs(template.FuncMap{"url": c.templateURL}).Parse(string(source))
		if err == nil {
			err = view.Execute(&buffer, data)
		}
	} else {
		// text/template does not escape JSON. The json helper uses encoding/json
		// to quote strings and serialize values correctly, including newlines.
		var functions texttemplate.FuncMap = texttemplate.FuncMap{
			"url": c.templateURL,
			"json": func(value interface{}) (string, error) {
				var encoded []byte
				var marshalError error
				encoded, marshalError = json.Marshal(value)
				return string(encoded), marshalError
			},
		}
		var view *texttemplate.Template
		view, err = texttemplate.New(filepath.Base(templatePath)).Funcs(functions).Parse(string(source))
		if err == nil {
			err = view.Execute(&buffer, data)
		}
		// Validate the finished document before committing any response bytes.
		if err == nil && !json.Valid(buffer.Bytes()) {
			return fmt.Errorf("view produced invalid JSON")
		}
	}
	if err != nil {
		return err
	}

	var contentType string = "text/html; charset=utf-8"
	if format == "json" {
		contentType = "application/json; charset=utf-8"
	}
	c.ResponseWriter.Header().Set("Content-Type", contentType)
	c.ResponseWriter.WriteHeader(http.StatusOK)
	// The buffer keeps template errors from sending a partial document. Network
	// failures can still happen after bytes have been committed to the connection.
	var writeError error
	_, writeError = io.Copy(c.ResponseWriter, &buffer)
	return writeError
}

func (c *Context) URL(name string, parameters ...map[string]string) (string, error) {
	if c.app == nil {
		return "", fmt.Errorf("URL generation requires an application context")
	}
	return c.app.URL(name, parameters...)
}

func (c *Context) templateURL(name string, pairs ...interface{}) (string, error) {
	if len(pairs)%2 != 0 {
		return "", fmt.Errorf("url requires parameter name/value pairs")
	}
	params := make(map[string]string)
	for i := 0; i < len(pairs); i += 2 {
		key, ok := pairs[i].(string)
		if !ok {
			return "", fmt.Errorf("url parameter names must be strings")
		}
		params[key] = fmt.Sprint(pairs[i+1])
	}
	return c.URL(name, params)
}

// HTTPError exposes a deliberate status/message rather than internal diagnostics.
func HTTPError(status int, message string) error { return &responseError{status, message} }

// ParamInt converts a member ID before it reaches GORM. Positive IDs avoid
// accidentally treating zero as an unspecified primary key.
func (c *Context) ParamInt(name string) (int, error) {
	var raw string = c.Params[name]
	var value int
	var err error
	value, err = strconv.Atoi(raw)
	if err != nil || value <= 0 {
		return 0, &responseError{status: 400, message: "Invalid parameter: " + name}
	}
	return value, nil
}

type responseError struct {
	status  int
	message string
}

func (e *responseError) Error() string { return e.message }

// BindJSON decodes one bounded object into an input struct pointer. Unknown
// fields are rejected so request payloads cannot silently assign model IDs.
func (c *Context) BindJSON(input interface{}) error {
	var mediaType string
	var err error
	mediaType, _, err = mime.ParseMediaType(c.Request.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return &responseError{415, "Expected application/json"}
	}
	var reader io.ReadCloser = http.MaxBytesReader(c.ResponseWriter, c.Request.Body, 1<<20)
	defer reader.Close()
	var decoder *json.Decoder = json.NewDecoder(reader)
	var raw json.RawMessage
	if err = decoder.Decode(&raw); err != nil {
		return &responseError{400, "Invalid JSON body"}
	}
	if len(raw) == 0 || raw[0] != '{' {
		return &responseError{400, "Expected JSON object"}
	}
	var extra interface{}
	if decoder.Decode(&extra) != io.EOF {
		return &responseError{400, "Expected one JSON object"}
	}
	decoder = json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(input); err != nil {
		return &responseError{400, "Invalid or unknown JSON fields"}
	}
	return nil
}

// Error maps intentional request errors and missing records while keeping raw
// database diagnostics in logs. Development exposes details for debugging only.
func (c *Context) writeError(err error) {
	if writer, ok := c.ResponseWriter.(*responseState); ok && writer.committed {
		log.Printf("bingo: error after response was committed: %v", err)
		return
	}

	var status int = 500
	var message string = "Internal server error"
	var public *responseError
	if errors.As(err, &public) {
		status = public.status
		message = public.message
	} else if errors.Is(err, gorm.ErrRecordNotFound) {
		status = 404
		message = "Record not found"
	} else if c.Development {
		message = err.Error()
	}
	log.Printf("bingo: %v", err)
	http.Error(c.ResponseWriter, message, status)
}
