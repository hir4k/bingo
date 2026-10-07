package bingo

import (
	"fmt"
	"net/http"
	"net/url"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

type Handler func(*Context) error
type Middleware func(http.Handler) http.Handler

type route struct {
	method      string
	path        string
	shape       string
	parts       []string
	handler     Handler
	httpHandler http.Handler
	middleware  []Middleware
}

type routingState struct {
	app    *App
	routes []*route
	names  map[string]*route
	frozen bool
}

// Groups share registrations but capture their own prefix and middleware.
type Router struct {
	state      *routingState
	prefix     string
	middleware []Middleware
	registered bool
}

func (r *Router) mutable() {
	if r.state.frozen {
		panic("bingo: routes are frozen after Handler or Run")
	}
}

func (r *Router) Use(middleware ...Middleware) {
	r.mutable()
	if r.registered {
		panic("bingo: declare Use before routes and groups")
	}
	for _, handler := range middleware {
		if handler == nil {
			panic("bingo: middleware cannot be nil")
		}
		r.middleware = append(r.middleware, handler)
	}
}

func validPath(value string, allowEmpty bool) bool {
	if value == "" {
		return allowEmpty
	}
	if value == "/" {
		return true
	}
	if !strings.HasPrefix(value, "/") || strings.HasSuffix(value, "/") || path.Clean(value) != value {
		return false
	}
	return !strings.ContainsAny(value, "?#%. \\\t\r\n")
}

func (r *Router) Group(prefix string, register func(*Router)) {
	r.mutable()
	if !validPath(prefix, true) || strings.Contains(prefix, ":") || register == nil {
		panic("bingo: invalid group declaration")
	}
	r.registered = true
	if prefix == "/" {
		prefix = ""
	}
	child := &Router{state: r.state, prefix: r.prefix + prefix, middleware: append([]Middleware(nil), r.middleware...)}
	register(child)
}

func (r *Router) Get(path string, handler Handler, name ...string) { r.add("GET", path, handler, name) }
func (r *Router) Post(path string, handler Handler, name ...string) {
	r.add("POST", path, handler, name)
}
func (r *Router) Put(path string, handler Handler, name ...string) { r.add("PUT", path, handler, name) }
func (r *Router) Patch(path string, handler Handler, name ...string) {
	r.add("PATCH", path, handler, name)
}
func (r *Router) Delete(path string, handler Handler, name ...string) {
	r.add("DELETE", path, handler, name)
}

func (r *Router) add(method, routePath string, handler Handler, names []string) {
	r.mutable()
	if !validPath(routePath, false) || handler == nil || len(names) > 1 {
		panic("bingo: invalid route declaration")
	}
	fullPath := r.prefix + routePath
	if routePath == "/" && r.prefix != "" {
		fullPath = r.prefix
	}
	parts := strings.Split(strings.TrimPrefix(fullPath, "/"), "/")
	shapeParts := append([]string(nil), parts...)
	seen := make(map[string]bool)
	for i, part := range parts {
		if !strings.Contains(part, ":") {
			continue
		}
		parameter := strings.TrimPrefix(part, ":")
		if !strings.HasPrefix(part, ":") || !commandName.MatchString(parameter) || seen[parameter] {
			panic("bingo: invalid or duplicate path parameter " + part)
		}
		seen[parameter] = true
		shapeParts[i] = ":"
	}
	shape := strings.Join(shapeParts, "/")
	for _, existing := range r.state.routes {
		sameMethod := existing.method == method || existing.method == "*" || method == "*"
		if sameMethod && existing.shape == shape {
			panic("bingo: duplicate route " + method + " " + fullPath)
		}
	}
	registration := &route{method: method, path: fullPath, parts: parts, shape: shape, handler: handler, middleware: append([]Middleware(nil), r.middleware...)}
	if len(names) == 1 {
		name := names[0]
		if name == "" {
			panic("bingo: route name cannot be empty")
		}
		for _, part := range strings.Split(name, ".") {
			if !commandName.MatchString(part) {
				panic("bingo: route names use snake_case segments separated by dots")
			}
		}
		if _, exists := r.state.names[name]; exists {
			panic("bingo: duplicate route name " + name)
		}
		r.state.names[name] = registration
	}
	r.registered = true
	r.state.routes = append(r.state.routes, registration)
}

func matchRoute(registration *route, parts []string) (map[string]string, bool) {
	if len(registration.parts) != len(parts) {
		return nil, false
	}
	params := make(map[string]string)
	for i, part := range registration.parts {
		if strings.HasPrefix(part, ":") {
			value, err := url.PathUnescape(parts[i])
			if err != nil || value == "" {
				return nil, false
			}
			params[part[1:]] = value
			continue
		}
		if part != parts[i] {
			return nil, false
		}
	}
	return params, true
}

func (r *Router) handler() http.Handler {
	r.state.frozen = true
	routes := append([]*route(nil), r.state.routes...)
	// Static segments win over parameters regardless of registration order.
	sort.SliceStable(routes, func(i, j int) bool {
		left, right := routes[i].parts, routes[j].parts
		for k := 0; k < len(left) && k < len(right); k++ {
			a, b := left[k], right[k]
			aParam, bParam := strings.HasPrefix(a, ":"), strings.HasPrefix(b, ":")
			if aParam != bParam {
				return !aParam
			}
			if !aParam && a != b {
				return a < b
			}
		}
		return len(left) < len(right)
	})
	handlers := make(map[*route]http.Handler)
	for _, registration := range routes {
		var handler http.Handler = registration.httpHandler
		if handler == nil {
			handler = http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
				cleanPath, format, _ := parsePath(request.URL.EscapedPath())
				params, _ := matchRoute(registration, strings.Split(strings.TrimPrefix(cleanPath, "/"), "/"))
				c := &Context{ResponseWriter: &responseState{ResponseWriter: w}, Request: request, Format: format, Params: params, ViewsDir: filepath.Join(r.state.app.Directory, "views"), Views: r.state.app.views, Development: r.state.app.development, app: r.state.app}
				if r.state.app.DB != nil {
					c.DB = r.state.app.DB.WithContext(request.Context())
				}
				if err := registration.handler(c); err != nil {
					c.writeError(err)
				}
			})
		}
		for i := len(registration.middleware) - 1; i >= len(r.middleware); i-- {
			handler = registration.middleware[i](handler)
		}
		handlers[registration] = handler
	}
	var dispatcher http.Handler = http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		// Protocol mounts dispatch before HTML/JSON format matching and pass
		// all methods to their transport handler, including GET and OPTIONS.
		for _, registration := range routes {
			if registration.httpHandler != nil && request.URL.EscapedPath() == registration.path {
				handlers[registration].ServeHTTP(w, request)
				return
			}
		}
		cleanPath, _, valid := parsePath(request.URL.EscapedPath())
		if !valid {
			http.NotFound(w, request)
			return
		}
		parts := strings.Split(strings.TrimPrefix(cleanPath, "/"), "/")
		var selected *route
		var allowed []string
		for _, registration := range routes {
			if registration.httpHandler != nil {
				continue
			}
			if _, matches := matchRoute(registration, parts); !matches {
				continue
			}
			if selected == nil {
				selected = registration
			}
			if registration.shape != selected.shape {
				continue
			}
			if registration.method == request.Method {
				handlers[registration].ServeHTTP(w, request)
				return
			}
			allowed = append(allowed, registration.method)
		}
		if selected == nil {
			http.NotFound(w, request)
			return
		}
		sort.Strings(allowed)
		w.Header().Set("Allow", strings.Join(allowed, ", "))
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	})
	for i := len(r.middleware) - 1; i >= 0; i-- {
		dispatcher = r.middleware[i](dispatcher)
	}
	return dispatcher
}

func parsePath(value string) (string, string, bool) {
	format := "html"
	extension := path.Ext(value)
	if extension != "" {
		if extension != ".html" && extension != ".json" {
			return "", "", false
		}
		value = strings.TrimSuffix(value, extension)
		format = extension[1:]
	}
	if value != "/" && (strings.HasSuffix(value, "/") || path.Clean(value) != value) {
		return "", "", false
	}
	if !strings.HasPrefix(value, "/") || strings.ContainsAny(value, "?# \\\t\r\n") {
		return "", "", false
	}
	return value, format, true
}

// URL resolves a complete route name without inferring names from groups.
// Escaping keeps parameter values inside one path segment, including slashes.
func (a *App) URL(name string, parameters ...map[string]string) (string, error) {
	registration, exists := a.root.state.names[name]
	if !exists {
		return "", fmt.Errorf("unknown route name %q", name)
	}
	if len(parameters) > 1 {
		return "", fmt.Errorf("URL accepts one parameter map")
	}
	var params map[string]string
	if len(parameters) == 1 {
		params = parameters[0]
	}
	parts := append([]string(nil), registration.parts...)
	for i, part := range parts {
		if !strings.HasPrefix(part, ":") {
			continue
		}
		key := part[1:]
		value, exists := params[key]
		if !exists || value == "" {
			return "", fmt.Errorf("route %q requires parameter %q", name, key)
		}
		if value == "." || value == ".." {
			return "", fmt.Errorf("invalid path parameter %q", key)
		}
		// Encode dots so a username ending in .json cannot select a format instead.
		parts[i] = strings.ReplaceAll(url.PathEscape(value), ".", "%2E")
	}
	return "/" + strings.Join(parts, "/"), nil
}
