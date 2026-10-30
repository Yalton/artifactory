package httpserver_test

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"testing"
	"time"

	"repo.billbert.co/artifactory/httpserver"
)

func freeAddr(t *testing.T) string {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().String()
}

func start(t *testing.T, h http.Handler, opts ...httpserver.Option) (string, context.CancelFunc, chan error) {
	addr := freeAddr(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- httpserver.Run(ctx, addr, h, opts...) }()
	for i := 0; i < 100; i++ {
		if c, err := net.Dial("tcp", addr); err == nil {
			c.Close()
			return "http://" + addr, cancel, done
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("server did not start")
	return "", nil, nil
}

func status(t *testing.T, url string) int {
	r, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	return r.StatusCode
}

func TestHealthzAndHandlerAndShutdown(t *testing.T) {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(418) })
	base, cancel, done := start(t, h)
	if s := status(t, base+"/healthz"); s != 200 {
		t.Fatalf("healthz %d", s)
	}
	if s := status(t, base+"/anything"); s != 418 {
		t.Fatalf("handler %d", s)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no shutdown")
	}
}

func TestHealthCheckFailure(t *testing.T) {
	fail := httpserver.WithHealthCheck(func(context.Context) error { return errors.New("down") })
	base, cancel, _ := start(t, http.NotFoundHandler(), fail)
	defer cancel()
	if s := status(t, base+"/healthz"); s != 503 {
		t.Fatalf("healthz %d", s)
	}
}

func TestListenError(t *testing.T) {
	l, _ := net.Listen("tcp", "127.0.0.1:0")
	defer l.Close()
	err := httpserver.Run(context.Background(), l.Addr().String(), http.NotFoundHandler())
	if err == nil {
		t.Fatal(fmt.Sprint("want listen error"))
	}
}
