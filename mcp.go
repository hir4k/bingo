package bingo

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
	"gorm.io/gorm"
)

// MCPServer owns one endpoint's explicitly registered tools. Protocol handling
// and typed JSON schemas are supplied by the official MCP SDK.
type MCPServer struct {
	server *sdk.Server
	app    *App
	names  map[string]bool
	frozen bool
}

// MCPContext is fresh for each tool call. Middleware values are available through
// Context; Request carries HTTP metadata. DB and Enqueue follow call cancellation.
type MCPContext struct {
	Context context.Context
	Request *http.Request
	DB      *gorm.DB
	app     *App
}

func (c *MCPContext) Enqueue(name string, payload any, options ...JobOptions) (string, error) {
	return c.app.enqueue(c.Context, c.DB, name, payload, options...)
}

type mcpRequestKey struct{}

// MCP mounts an exact protocol endpoint with the current group's middleware.
// Format suffixes and child URLs do not alias the endpoint. A mount reserves
// every method on its path, preventing collisions with normal HTTP routes.
func (r *Router) MCP(routePath string, register func(*MCPServer)) {
	r.mutable()
	if register == nil || strings.Contains(routePath, ":") {
		panic("bingo: MCP requires a static path and registration function")
	}
	r.add("*", routePath, func(*Context) error { return nil }, nil)
	registration := r.state.routes[len(r.state.routes)-1]
	server := &MCPServer{app: r.state.app, names: make(map[string]bool), server: sdk.NewServer(&sdk.Implementation{Name: "bingo", Version: Version}, nil)}
	register(server)
	server.frozen = true
	transport := sdk.NewStreamableHTTPHandler(func(*http.Request) *sdk.Server { return server.server }, &sdk.StreamableHTTPOptions{Stateless: true, JSONResponse: true, MaxRequestBodyBytes: 1 << 20, PropagateRequestCancellation: true})
	protected := http.NewCrossOriginProtection().Handler(transport)
	registration.httpHandler = http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		ctx := context.WithValue(request.Context(), mcpRequestKey{}, request)
		protected.ServeHTTP(w, request.WithContext(ctx))
	})
	registration.handler = nil
}

// AddTool checks the Go handler's input/output types at compile time. The SDK
// infers schemas and validates arguments before calling the handler. Generic
// functions are used because Go methods cannot declare their own type parameters.
func AddTool[In, Out any](server *MCPServer, name, description string, handler func(*MCPContext, In) (Out, error)) {
	if server == nil || server.frozen {
		panic("bingo: MCP registration is closed")
	}
	if !commandName.MatchString(name) || strings.TrimSpace(description) == "" || handler == nil {
		panic("bingo: MCP tools require a snake_case name, description, and handler")
	}
	if server.names[name] {
		panic("bingo: duplicate MCP tool " + name)
	}
	sdk.AddTool(server.server, &sdk.Tool{Name: name, Description: description}, func(ctx context.Context, request *sdk.CallToolRequest, input In) (result *sdk.CallToolResult, output Out, err error) {
		defer func() {
			if value := recover(); value != nil {
				err = fmt.Errorf("MCP tool %s panicked: %v", name, value)
			}
			if err != nil {
				err = mcpToolError(err, server.app.development)
			}
		}()
		callContext, cancel := context.WithCancel(ctx)
		defer cancel()
		httpRequest, _ := ctx.Value(mcpRequestKey{}).(*http.Request)
		// Older MCP protocol versions do not propagate disconnect cancellation in
		// the SDK. Bingo binds both versions to the originating HTTP request.
		if httpRequest != nil {
			stop := context.AfterFunc(httpRequest.Context(), cancel)
			defer stop()
		}
		c := &MCPContext{Context: callContext, Request: httpRequest, app: server.app}
		if server.app.DB != nil {
			c.DB = server.app.DB.WithContext(callContext)
		}
		output, err = handler(c, input)
		if err == nil {
			err = callContext.Err()
		}
		return nil, output, err
	})
	server.names[name] = true
}

func mcpToolError(err error, development bool) error {
	log.Printf("bingo: MCP: %v", err)
	var public *responseError
	if errors.As(err, &public) {
		return errors.New(public.message)
	}
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return errors.New("Record not found")
	}
	if errors.Is(err, context.Canceled) {
		return context.Canceled
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return context.DeadlineExceeded
	}
	if development {
		return errors.New(err.Error())
	}
	return errors.New("Internal tool error")
}
