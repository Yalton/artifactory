// Package httpserver runs an http.Handler with a health endpoint and graceful shutdown.
package httpserver

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os/signal"
	"syscall"
	"time"
)

// Option configures Run.
type Option func(*options)

type options struct {
	health func(context.Context) error
}

// WithHealthCheck makes GET /healthz return 503 when fn returns an error.
func WithHealthCheck(fn func(context.Context) error) Option {
	return func(o *options) { o.health = fn }
}

// Run serves h on addr, adding GET /healthz (200 by default). It returns nil after
// a graceful shutdown, triggered by ctx being cancelled or SIGINT/SIGTERM.
func Run(ctx context.Context, addr string, h http.Handler, opts ...Option) error {
	var o options
	for _, opt := range opts {
		opt(&o)
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(ctx, syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		if o.health != nil {
			if err := o.health(r.Context()); err != nil {
				http.Error(w, err.Error(), http.StatusServiceUnavailable)
				return
			}
		}
		w.WriteHeader(http.StatusOK)
	})
	mux.Handle("/", h)

	srv := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	errc := make(chan error, 1)
	go func() { errc <- srv.Serve(ln) }()
	select {
	case err := <-errc:
		return err
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return err
	}
	if err := <-errc; !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
