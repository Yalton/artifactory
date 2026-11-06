package provider

import (
	"context"
	"errors"
	"testing"
)

// tagStub is a Provider whose Tags returns fixed values.
type tagStub struct {
	tags []string
	err  error
}

func (s tagStub) Spec() string                                   { return "stub:" }
func (s tagStub) List(context.Context) ([]string, error)         { return nil, nil }
func (s tagStub) Tags(context.Context, string) ([]string, error) { return s.tags, s.err }
func (s tagStub) ReadFile(context.Context, string, string, string) ([]byte, error) {
	return nil, ErrNotFound
}
func (s tagStub) Ensure(context.Context, string) (string, error) { return "", nil }

func TestHasTag(t *testing.T) {
	boom := errors.New("boom")
	cases := []struct {
		name string
		p    tagStub
		want bool
		err  error
	}{
		{"present", tagStub{tags: []string{"v1.0.0", "v1.1.0"}}, true, nil},
		{"absent", tagStub{tags: []string{"v1.0.0"}}, false, nil},
		{"missing repo", tagStub{err: ErrNotFound}, false, nil},
		{"other error", tagStub{err: boom}, false, boom},
	}
	for _, c := range cases {
		got, err := HasTag(context.Background(), c.p, "m", "v1.1.0")
		if got != c.want || !errors.Is(err, c.err) {
			t.Errorf("%s: HasTag = %v, %v; want %v, %v", c.name, got, err, c.want, c.err)
		}
	}
}
