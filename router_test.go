package bingo

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func testHandler(c *Context) error {
	_, err := fmt.Fprintf(c.ResponseWriter, "1:%s:%s", c.Format, c.Params["id"])
	return err
}

func registerTestRoutes(r *Router) {
	r.Get("/todos", testHandler)
	r.Get("/todos/:id", testHandler)
	r.Get("/todos/new", func(c *Context) error { c.Params = map[string]string{}; return testHandler(c) })
	r.Get("/todos/:id/edit", testHandler)
	r.Post("/todos", testHandler)
	r.Patch("/todos/:id", testHandler)
	r.Put("/todos/:id", testHandler)
	r.Delete("/todos/:id", testHandler)
}

func TestExplicitRoutes(t *testing.T) {
	var app *App = New()
	app.Routes(func(root *Router) {
		root.Group("/api", func(api *Router) { registerTestRoutes(api) })
	})
	var handler http.Handler = app.Handler()
	var cases = []struct {
		method, path, body string
		status             int
	}{
		{"GET", "/api/todos", "1:html:", 200}, {"GET", "/api/todos.json", "1:json:", 200},
		{"GET", "/api/todos/1.json", "1:json:1", 200}, {"GET", "/api/todos/new", "1:html:", 200},
		{"GET", "/api/todos/1/edit", "1:html:1", 200}, {"POST", "/api/todos", "1:html:", 200},
		{"PATCH", "/api/todos/1", "1:html:1", 200}, {"PUT", "/api/todos/1", "1:html:1", 200},
		{"DELETE", "/api/todos/1", "1:html:1", 200}, {"POST", "/api/todos/new", "", 405},
		{"GET", "/api/todos/1/extra", "", 404}, {"GET", "/api/todos/", "", 404}, {"GET", "/api/todos.xml", "", 404},
		{"GET", "/api/todos/1.json?x=yes", "1:json:1", 200}, {"GET", "/missing", "", 404},
	}
	for _, tc := range cases {
		t.Run(tc.method+tc.path, func(t *testing.T) {
			var response *httptest.ResponseRecorder = httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest(tc.method, tc.path, nil))
			if response.Code != tc.status {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if tc.body != "" && response.Body.String() != tc.body {
				t.Fatalf("body = %q", response.Body.String())
			}
			if tc.status == 405 && response.Header().Get("Allow") != "GET" {
				t.Fatal("incorrect Allow")
			}
		})
	}
	var workers sync.WaitGroup
	for id := 1; id <= 20; id++ {
		workers.Add(1)
		go func(id int) {
			defer workers.Done()
			var response = httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest("GET", fmt.Sprintf("/api/todos/%d.json", id), nil))
			if response.Body.String() != fmt.Sprintf("1:json:%d", id) {
				t.Errorf("request state reused: %s", response.Body.String())
			}
		}(id)
	}
	workers.Wait()
}

func TestMiddlewareScopes(t *testing.T) {
	var events []string
	var middleware = func(name string) Middleware {
		return func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				events = append(events, name+" before")
				next.ServeHTTP(w, r)
				events = append(events, name+" after")
			})
		}
	}
	var app *App = New()
	app.Routes(func(root *Router) {
		root.Use(middleware("root"))
		root.Group("/api", func(api *Router) {
			api.Use(middleware("auth"))
			registerTestRoutes(api)
			api.Group("", func(reports *Router) {
				reports.Use(middleware("audit"))
				reports.Get("/reports", testHandler)
			})
		})
	})
	var handler http.Handler = app.Handler()
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/api/reports", nil))
	if strings.Join(events, ",") != "root before,auth before,audit before,audit after,auth after,root after" {
		t.Fatal(events)
	}
	events = nil
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/api/todos", nil))
	if strings.Join(events, ",") != "root before,auth before,auth after,root after" {
		t.Fatal(events)
	}
}

func TestMiddlewareCanStopDispatch(t *testing.T) {
	var calls int
	var app *App = New()
	app.Routes(func(root *Router) {
		root.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "Denied", 401) })
		})
		root.Get("/todos", func(c *Context) error { calls++; return testHandler(c) })
	})
	var response = httptest.NewRecorder()
	app.Handler().ServeHTTP(response, httptest.NewRequest("GET", "/todos", nil))
	if response.Code != 401 || calls != 0 {
		t.Fatalf("status %d, calls %d", response.Code, calls)
	}
}

func TestRegistrationRules(t *testing.T) {
	for _, scenario := range []string{"late use", "duplicate", "frozen", "invalid group", "invalid resource"} {
		t.Run(scenario, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Fatal("registration should fail")
				}
			}()
			var app *App = New()
			switch scenario {
			case "late use":
				app.root.Get("/todos", testHandler)
				app.root.Use(func(h http.Handler) http.Handler { return h })
			case "duplicate":
				app.root.Get("/todos", testHandler)
				app.root.Get("/todos", testHandler)
			case "frozen":
				app.Handler()
				app.root.Get("/todos", testHandler)
			case "invalid group":
				app.root.Group("/api/", func(r *Router) {})
			case "invalid resource":
				app.root.Get("/todos.json", testHandler)
			}
		})
	}
}

func dbHandler(c *Context) error {
	if c.DB == nil || c.DB.Statement.Context != c.Request.Context() {
		panic("request context missing")
	}
	var value int
	if err := c.DB.Raw("SELECT 1").Scan(&value).Error; err != nil {
		return err
	}
	_, err := fmt.Fprint(c.ResponseWriter, value)
	return err
}

func TestGORMRequestContext(t *testing.T) {
	var app *App = New()
	var err error
	app.DB, err = OpenDatabase(DatabaseConfig{Driver: "sqlite", Database: filepath.Join(t.TempDir(), "test.sqlite3")})
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := app.DB.DB()
	defer pool.Close()
	app.Routes(func(root *Router) { root.Get("/todos", dbHandler) })
	var handler http.Handler = app.Handler()
	var ctx context.Context
	var cancel context.CancelFunc
	ctx, cancel = context.WithCancel(context.Background())
	cancel()
	var response = httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest("GET", "/todos", nil).WithContext(ctx))
	if response.Code != 500 {
		t.Fatalf("canceled query status %d", response.Code)
	}
	var value int
	if err = app.DB.Raw("SELECT 1").Scan(&value).Error; err != nil || value != 1 {
		t.Fatalf("shared context changed: %v", err)
	}
}

func TestRootMiddlewareSeesUnmatchedPaths(t *testing.T) {
	var app *App = New()
	var calls int
	app.Routes(func(root *Router) {
		root.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; next.ServeHTTP(w, r) })
		})
	})
	var response = httptest.NewRecorder()
	app.Handler().ServeHTTP(response, httptest.NewRequest("GET", "/missing", nil))
	if calls != 1 || response.Code != 404 {
		t.Fatalf("calls %d, status %d", calls, response.Code)
	}
}

func TestNamedRoutesAndStringParameters(t *testing.T) {
	app := New()
	var captured string
	app.Routes(func(root *Router) {
		root.Group("/api", func(api *Router) {
			api.Get("/users/:username", func(c *Context) error {
				captured = c.Params["username"]
				c.Params["username"] = "changed"
				target, err := c.URL("users.show", map[string]string{"username": captured})
				if err != nil {
					return err
				}
				_, err = fmt.Fprint(c.ResponseWriter, target+":"+c.Format)
				return err
			}, "users.show")
			api.Get("/users", testHandler, "users.index")
		})
	})
	handler := app.Handler()
	for _, name := range []string{"alice", "alice.json", "a/b ?#%", "日本語"} {
		target, err := app.URL("users.show", map[string]string{"username": name})
		if err != nil {
			t.Fatal(err)
		}
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", target+".json", nil))
		if response.Code != 200 || captured != name || response.Body.String() != target+":json" {
			t.Fatalf("%q: %d %q %q", name, response.Code, captured, response.Body.String())
		}
	}
	target, err := app.URL("users.index")
	if err != nil || target != "/api/users" {
		t.Fatalf("%s %v", target, err)
	}
	for _, name := range []string{"missing", "users.show"} {
		if _, err := app.URL(name); err == nil {
			t.Fatal("accepted unknown name or missing parameter")
		}
	}
}

func TestNamedRouteRegistrationFailures(t *testing.T) {
	for _, scenario := range []string{"duplicate name", "same pattern", "duplicate parameter", "bad parameter", "bad name", "nil handler", "multiple names"} {
		t.Run(scenario, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Fatal("invalid declaration accepted")
				}
			}()
			r := New().root
			switch scenario {
			case "duplicate name":
				r.Get("/a", testHandler, "same")
				r.Post("/b", testHandler, "same")
			case "same pattern":
				r.Get("/a/:id", testHandler)
				r.Get("/a/:name", testHandler)
			case "duplicate parameter":
				r.Get("/a/:id/:id", testHandler)
			case "bad parameter":
				r.Get("/a/:user-name", testHandler)
			case "bad name":
				r.Get("/a", testHandler, "Users.show")
			case "nil handler":
				r.Get("/a", nil)
			case "multiple names":
				r.Get("/a", testHandler, "a", "b")
			}
		})
	}
}

func TestReturnedErrorsAndPanics(t *testing.T) {
	for _, development := range []bool{false, true} {
		app := New()
		app.development = development
		app.Routes(func(r *Router) {
			r.Get("/error", func(c *Context) error { return fmt.Errorf("private failure") })
			r.Get("/public", func(c *Context) error { return HTTPError(422, "Invalid username") })
			r.Get("/panic", func(c *Context) error { panic("private failure") })
			r.Get("/written", func(c *Context) error {
				_, _ = fmt.Fprint(c.ResponseWriter, "done")
				return fmt.Errorf("private failure")
			})
		})
		handler := app.Handler()
		for _, route := range []string{"/error", "/panic"} {
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest("GET", route, nil))
			if response.Code != 500 || strings.Contains(response.Body.String(), "private failure") != development {
				t.Fatalf("%s: %d %s", route, response.Code, response.Body.String())
			}
		}
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", "/public", nil))
		if response.Code != 422 || !strings.Contains(response.Body.String(), "Invalid username") {
			t.Fatal(response)
		}
		response = httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest("GET", "/written", nil))
		if response.Body.String() != "done" {
			t.Fatal(response.Body.String())
		}
	}
}
