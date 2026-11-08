// Package kvstore is a small string key-value store kept in one JSON file.
package kvstore

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sync"
)

// Store is safe for concurrent use.
type Store struct {
	mu   sync.RWMutex
	path string
	data map[string]string
}

// Open loads the store at path, creating the file (and parent directories) if missing.
func Open(path string) (*Store, error) {
	s := &Store{path: path, data: map[string]string{}}
	b, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return nil, fmt.Errorf("kvstore: %w", err)
		}
		if err := s.flush(); err != nil {
			return nil, err
		}
	case err != nil:
		return nil, fmt.Errorf("kvstore: %w", err)
	case len(b) > 0:
		if err := json.Unmarshal(b, &s.data); err != nil {
			return nil, fmt.Errorf("kvstore: %s: %w", path, err)
		}
		if s.data == nil { // a file containing `null` decodes to a nil map
			s.data = map[string]string{}
		}
	}
	return s, nil
}

// Get returns the value for key and whether it exists.
func (s *Store) Get(key string) (string, bool, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.data[key]
	return v, ok, nil
}

// PutIfAbsent stores val under key unless key exists. It reports whether it stored.
func (s *Store) PutIfAbsent(key, val string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[key]; ok {
		return false, nil
	}
	s.data[key] = val
	if err := s.flush(); err != nil {
		delete(s.data, key)
		return false, err
	}
	return true, nil
}

// Put stores val under key, replacing any existing value.
func (s *Store) Put(key, val string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, had := s.data[key]
	s.data[key] = val
	if err := s.flush(); err != nil {
		if had {
			s.data[key] = old
		} else {
			delete(s.data, key)
		}
		return err
	}
	return nil
}

// Delete removes key. It reports whether the key existed; the file is rewritten only if it did.
func (s *Store) Delete(key string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.data[key]
	if !ok {
		return false, nil
	}
	delete(s.data, key)
	if err := s.flush(); err != nil {
		s.data[key] = old
		return false, err
	}
	return true, nil
}

// Close releases the store. Every write is already on disk.
func (s *Store) Close() error { return nil }

// flush rewrites the file atomically (temp file, then rename). Caller holds the lock.
func (s *Store) flush() error {
	b, err := json.Marshal(s.data)
	if err != nil {
		return fmt.Errorf("kvstore: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.path), ".kvstore-*")
	if err != nil {
		return fmt.Errorf("kvstore: %w", err)
	}
	_, werr := tmp.Write(b)
	serr := tmp.Sync()
	cerr := tmp.Close()
	if err := errors.Join(werr, serr, cerr); err != nil {
		os.Remove(tmp.Name())
		return fmt.Errorf("kvstore: %w", err)
	}
	if err := os.Rename(tmp.Name(), s.path); err != nil {
		os.Remove(tmp.Name())
		return fmt.Errorf("kvstore: %w", err)
	}
	return syncDir(filepath.Dir(s.path))
}

// syncDir fsyncs a directory so a completed rename survives a crash.
func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return fmt.Errorf("kvstore: %w", err)
	}
	serr := d.Sync()
	cerr := d.Close()
	if err := errors.Join(serr, cerr); err != nil {
		return fmt.Errorf("kvstore: %w", err)
	}
	return nil
}
