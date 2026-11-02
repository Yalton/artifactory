// Package config fills a struct from environment variables, an optional
// key=value file and struct-tag defaults.
package config

import (
	"bufio"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"
)

// Load fills dst, a pointer to a struct whose fields carry `env:"NAME"` and an
// optional `default:"value"` tag. The value for a field comes from, in order:
// the environment variable PREFIX_NAME, the line NAME=value in file, the default.
// file may be "" or missing. Supported field types: string, int, bool,
// float64, time.Duration.
func Load(prefix string, dst any, file string) error {
	v := reflect.ValueOf(dst)
	if v.Kind() != reflect.Pointer || v.IsNil() || v.Elem().Kind() != reflect.Struct {
		return errors.New("config: dst must be a non-nil pointer to a struct")
	}
	fileVals, err := readFile(file)
	if err != nil {
		return err
	}
	v = v.Elem()
	t := v.Type()
	for i := 0; i < t.NumField(); i++ {
		name := t.Field(i).Tag.Get("env")
		if name == "" {
			continue
		}
		val, ok := os.LookupEnv(prefix + "_" + name)
		if !ok {
			val, ok = fileVals[name]
		}
		if !ok {
			val, ok = t.Field(i).Tag.Lookup("default")
		}
		if !ok {
			continue
		}
		if err := set(v.Field(i), val); err != nil {
			return fmt.Errorf("config: %s_%s: %w", prefix, name, err)
		}
	}
	return nil
}

func readFile(file string) (map[string]string, error) {
	out := map[string]string{}
	if file == "" {
		return out, nil
	}
	f, err := os.Open(file)
	if errors.Is(err, fs.ErrNotExist) {
		return out, nil
	}
	if err != nil {
		return nil, fmt.Errorf("config: %w", err)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			return nil, fmt.Errorf("config: %s: bad line %q", file, line)
		}
		out[strings.TrimSpace(k)] = strings.TrimSpace(v)
	}
	return out, sc.Err()
}

func set(f reflect.Value, s string) error {
	if f.Type() == reflect.TypeOf(time.Duration(0)) {
		d, err := time.ParseDuration(s)
		f.SetInt(int64(d))
		return err
	}
	switch f.Kind() {
	case reflect.String:
		f.SetString(s)
	case reflect.Int:
		n, err := strconv.Atoi(s)
		if err != nil {
			return err
		}
		f.SetInt(int64(n))
	case reflect.Bool:
		b, err := strconv.ParseBool(s)
		if err != nil {
			return err
		}
		f.SetBool(b)
	case reflect.Float64:
		x, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return err
		}
		f.SetFloat(x)
	default:
		return fmt.Errorf("unsupported field type %s", f.Type())
	}
	return nil
}
