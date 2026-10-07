package bingo

import (
	"context"
	"encoding/json"
	"fmt"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func mcpCall(t *testing.T, handler http.Handler, path, method string, params any) map[string]any {
	t.Helper()
	body, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest("POST", path, strings.NewReader(string(body)))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json, text/event-stream")
	request.Header.Set("MCP-Protocol-Version", "2025-11-25")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 200 {
		t.Fatalf("MCP %s: %d %s", method, response.Code, response.Body.String())
	}
	var result map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatalf("MCP JSON: %v %s", err, response.Body.String())
	}
	return result
}

type mcpEchoInput struct {
	Name string `json:"name"`
}
type mcpEchoOutput struct {
	Greeting string `json:"greeting"`
}

func TestMCPDiscoveryValidationAndCalls(t *testing.T) {
	app := New()
	var calls atomic.Int32
	app.Routes(func(root *Router) {
		root.MCP("/mcp", func(server *MCPServer) {
			AddTool(server, "greet", "Greet a person", func(c *MCPContext, input mcpEchoInput) (mcpEchoOutput, error) {
				calls.Add(1)
				return mcpEchoOutput{Greeting: "Hello " + input.Name}, nil
			})
		})
	})
	handler := app.Handler()
	discovery := mcpCall(t, handler, "/mcp", "tools/list", map[string]any{})
	result := discovery["result"].(map[string]any)
	tools := result["tools"].([]any)
	if len(tools) != 1 {
		t.Fatal(tools)
	}
	tool := tools[0].(map[string]any)
	if tool["name"] != "greet" || tool["inputSchema"] == nil || tool["outputSchema"] == nil {
		t.Fatal(tool)
	}
	response := mcpCall(t, handler, "/mcp", "tools/call", map[string]any{"name": "greet", "arguments": map[string]any{"name": "Bingo"}})
	structured := response["result"].(map[string]any)["structuredContent"].(map[string]any)
	if structured["greeting"] != "Hello Bingo" {
		t.Fatal(response)
	}
	for _, args := range []map[string]any{{"name": 42}, {"name": "Bingo", "invented": true}, {}} {
		response = mcpCall(t, handler, "/mcp", "tools/call", map[string]any{"name": "greet", "arguments": args})
		if response["result"].(map[string]any)["isError"] != true {
			t.Fatalf("invalid args accepted: %v", response)
		}
	}
	if calls.Load() != 1 {
		t.Fatal("invalid input reached handler")
	}
	response = mcpCall(t, handler, "/mcp", "tools/call", map[string]any{"name": "missing", "arguments": map[string]any{}})
	if response["error"] == nil {
		t.Fatal("unknown tool accepted")
	}
	for _, path := range []string{"/mcp.json", "/mcp.html", "/mcp/child"} {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest("POST", path, nil))
		if recorder.Code != 404 {
			t.Fatalf("unexpected MCP alias %s: %d", path, recorder.Code)
		}
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest("GET", "/mcp", nil))
	if recorder.Code != 405 {
		t.Fatal("GET transport method was not handled")
	}
}

func TestMCPGroupMiddlewareDatabaseAndEnqueue(t *testing.T) {
	app, db := jobTestApp(t)
	app.DB = db
	app.Jobs(func(j *Jobs) { j.Register("do_work", func(*JobContext) error { return nil }) })
	type principalKey struct{}
	var middlewareCalls atomic.Int32
	app.Routes(func(root *Router) {
		root.Use(func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { middlewareCalls.Add(1); next.ServeHTTP(w, r) })
		})
		root.Group("/api", func(api *Router) {
			api.Use(func(next http.Handler) http.Handler {
				return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if r.Header.Get("Authorization") != "Bearer test" {
						http.Error(w, "Unauthorized", 401)
						return
					}
					next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), principalKey{}, "user_42")))
				})
			})
			api.MCP("/mcp", func(server *MCPServer) {
				AddTool(server, "enqueue_work", "Queue test work", func(c *MCPContext, input struct{}) (struct {
					ID string `json:"id"`
				}, error) {
					if c.Context.Value(principalKey{}) != "user_42" || c.Request == nil || c.DB == nil {
						return struct {
							ID string `json:"id"`
						}{}, fmt.Errorf("middleware or database context missing")
					}
					if c.DB.Statement.Context != c.Context {
						return struct {
							ID string `json:"id"`
						}{}, fmt.Errorf("database not bound to call context")
					}
					id, err := c.Enqueue("do_work", nil)
					return struct {
						ID string `json:"id"`
					}{ID: id}, err
				})
			})
		})
	})
	handler := app.Handler()
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/mcp", nil))
	if recorder.Code != 401 {
		t.Fatal("authentication bypassed")
	}
	authorized := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Header.Set("Authorization", "Bearer test")
		handler.ServeHTTP(w, r)
	})
	response := mcpCall(t, authorized, "/api/mcp", "tools/call", map[string]any{"name": "enqueue_work", "arguments": map[string]any{}})
	result := response["result"].(map[string]any)
	if result["isError"] == true {
		t.Fatal(response)
	}
	id := result["structuredContent"].(map[string]any)["id"].(string)
	var count int64
	if err := db.Table("bingo_jobs").Where("id=?", id).Count(&count).Error; err != nil || count != 1 {
		t.Fatalf("enqueued jobs: %d %v", count, err)
	}
	if middlewareCalls.Load() != 2 {
		t.Fatal("root middleware ran more than once per request")
	}
}

func TestMCPErrorsAndPanicsDoNotCrashServer(t *testing.T) {
	app := New()
	app.Routes(func(root *Router) {
		root.MCP("/mcp", func(server *MCPServer) {
			AddTool(server, "fail", "Fail deliberately", func(*MCPContext, struct{}) (mcpEchoOutput, error) {
				return mcpEchoOutput{}, fmt.Errorf("private database details")
			})
			AddTool(server, "panic_tool", "Panic deliberately", func(*MCPContext, struct{}) (mcpEchoOutput, error) { panic("private panic details") })
			AddTool(server, "denied", "Deliberate public error", func(*MCPContext, struct{}) (mcpEchoOutput, error) {
				return mcpEchoOutput{}, HTTPError(403, "Access denied")
			})
		})
	})
	handler := app.Handler()
	for _, name := range []string{"fail", "panic_tool", "denied"} {
		response := mcpCall(t, handler, "/mcp", "tools/call", map[string]any{"name": name, "arguments": map[string]any{}})
		result := response["result"].(map[string]any)
		encoded, _ := json.Marshal(result)
		if result["isError"] != true || strings.Contains(string(encoded), "private") {
			t.Fatal(response)
		}
		if name == "denied" && !strings.Contains(string(encoded), "Access denied") {
			t.Fatal(response)
		}
	}
}

func TestMCPRequestCancellation(t *testing.T) {
	app := New()
	entered := make(chan struct{})
	stopped := make(chan struct{})
	app.Routes(func(root *Router) {
		root.MCP("/mcp", func(server *MCPServer) {
			AddTool(server, "wait", "Wait for cancellation", func(c *MCPContext, _ struct{}) (mcpEchoOutput, error) {
				close(entered)
				<-c.Context.Done()
				close(stopped)
				return mcpEchoOutput{}, c.Context.Err()
			})
		})
	})
	handler := app.Handler()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	request := httptest.NewRequest("POST", "/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"wait","arguments":{}}}`)).WithContext(ctx)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json, text/event-stream")
	request.Header.Set("MCP-Protocol-Version", "2025-11-25")
	done := make(chan struct{})
	go func() { defer close(done); handler.ServeHTTP(httptest.NewRecorder(), request) }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("tool did not start")
	}
	cancel()
	select {
	case <-stopped:
	case <-time.After(5 * time.Second):
		t.Fatal("tool did not receive cancellation")
	}
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("MCP request did not finish")
	}
}

type mcpHandlerTransport struct{ handler http.Handler }

func (transport mcpHandlerTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	response := httptest.NewRecorder()
	transport.handler.ServeHTTP(response, request)
	result := response.Result()
	result.Request = request
	return result, nil
}

func TestMCPOfficialSDKClient(t *testing.T) {
	app := New()
	app.Routes(func(root *Router) {
		root.MCP("/mcp", func(server *MCPServer) {
			AddTool(server, "greet", "Greet a person", func(c *MCPContext, input mcpEchoInput) (mcpEchoOutput, error) {
				return mcpEchoOutput{Greeting: "Hello " + input.Name}, nil
			})
		})
	})
	client := sdk.NewClient(&sdk.Implementation{Name: "bingo-test", Version: "1"}, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	session, err := client.Connect(ctx, &sdk.StreamableClientTransport{Endpoint: "http://bingo.test/mcp", HTTPClient: &http.Client{Transport: mcpHandlerTransport{handler: app.Handler()}}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	tools, err := session.ListTools(ctx, &sdk.ListToolsParams{})
	if err != nil || len(tools.Tools) != 1 {
		t.Fatalf("SDK discovery: %v %v", tools, err)
	}
	result, err := session.CallTool(ctx, &sdk.CallToolParams{Name: "greet", Arguments: map[string]any{"name": "SDK"}})
	if err != nil || result.IsError {
		t.Fatalf("SDK call: %v %v", result, err)
	}
	encoded, _ := json.Marshal(result.StructuredContent)
	if !strings.Contains(string(encoded), "Hello SDK") {
		t.Fatal(result)
	}
}

func TestMCPRegistrationRules(t *testing.T) {
	handler := func(*MCPContext, struct{}) (mcpEchoOutput, error) { return mcpEchoOutput{}, nil }
	cases := map[string]func(*Router){
		"duplicate_tool": func(root *Router) {
			root.MCP("/mcp", func(s *MCPServer) { AddTool(s, "greet", "Greet", handler); AddTool(s, "greet", "Greet", handler) })
		},
		"bad_name":            func(root *Router) { root.MCP("/mcp", func(s *MCPServer) { AddTool(s, "Not_snake", "Greet", handler) }) },
		"missing_description": func(root *Router) { root.MCP("/mcp", func(s *MCPServer) { AddTool(s, "greet", "", handler) }) },
		"nil_handler": func(root *Router) {
			root.MCP("/mcp", func(s *MCPServer) {
				AddTool(s, "greet", "Greet", (func(*MCPContext, struct{}) (mcpEchoOutput, error))(nil))
			})
		},
		"input_not_object": func(root *Router) {
			root.MCP("/mcp", func(s *MCPServer) {
				AddTool(s, "greet", "Greet", func(*MCPContext, string) (mcpEchoOutput, error) { return mcpEchoOutput{}, nil })
			})
		},
		"duplicate_mount": func(root *Router) { root.MCP("/mcp", func(*MCPServer) {}); root.MCP("/mcp", func(*MCPServer) {}) },
		"http_collision": func(root *Router) {
			root.Get("/mcp", func(*Context) error { return nil })
			root.MCP("/mcp", func(*MCPServer) {})
		},
		"reverse_http_collision": func(root *Router) {
			root.MCP("/mcp", func(*MCPServer) {})
			root.Post("/mcp", func(*Context) error { return nil })
		},
		"parameter_mount":  func(root *Router) { root.MCP("/:name", func(*MCPServer) {}) },
		"nil_registration": func(root *Router) { root.MCP("/mcp", nil) },
	}
	for name, register := range cases {
		t.Run(name, func(t *testing.T) {
			defer func() {
				if recover() == nil {
					t.Fatal("invalid registration accepted")
				}
			}()
			New().Routes(register)
		})
	}
	t.Run("late_tool", func(t *testing.T) {
		app := New()
		var saved *MCPServer
		app.Routes(func(root *Router) { root.MCP("/mcp", func(s *MCPServer) { saved = s }) })
		defer func() {
			if recover() == nil {
				t.Fatal("late registration accepted")
			}
		}()
		AddTool(saved, "greet", "Greet", handler)
	})
}

func TestMCPOriginAndBodyLimits(t *testing.T) {
	app := New()
	app.Routes(func(root *Router) { root.MCP("/mcp", func(*MCPServer) {}) })
	handler := app.Handler()
	for _, test := range []struct {
		origin, body string
		status       int
	}{
		{origin: "https://untrusted.example", body: `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, status: 403},
		{body: strings.Repeat(" ", 1<<20) + `{}`, status: 413},
	} {
		request := httptest.NewRequest("POST", "http://bingo.test/mcp", strings.NewReader(test.body))
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("Accept", "application/json, text/event-stream")
		request.Header.Set("MCP-Protocol-Version", "2025-11-25")
		if test.origin != "" {
			request.Header.Set("Origin", test.origin)
		}
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != test.status {
			t.Fatalf("HTTP protection: want %d got %d %s", test.status, response.Code, response.Body.String())
		}
	}
}
