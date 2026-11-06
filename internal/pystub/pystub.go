// Package pystub writes minimal python wheels for tests. It builds the zip
// by hand, so tests need no build backend and no network.
package pystub

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Wheel writes <dist>-<version>-py3-none-any.whl into dir. pkg is the import
// package; files maps paths inside it (like "module.yaml") to content, and
// an __init__.py is added when files has none.
func Wheel(dir, name, version, pkg string, files map[string]string) (string, error) {
	dist := strings.ReplaceAll(name, "-", "_")
	info := dist + "-" + version + ".dist-info"
	all := map[string]string{}
	for p, c := range files {
		all[pkg+"/"+p] = c
	}
	if _, ok := files["__init__.py"]; !ok {
		all[pkg+"/__init__.py"] = ""
	}
	all[info+"/METADATA"] = "Metadata-Version: 2.1\nName: " + name + "\nVersion: " + version + "\n"
	all[info+"/WHEEL"] = "Wheel-Version: 1.0\nGenerator: pystub\nRoot-Is-Purelib: true\nTag: py3-none-any\n"

	paths := make([]string, 0, len(all))
	for p := range all {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	var record strings.Builder
	for _, p := range paths {
		sum := sha256.Sum256([]byte(all[p]))
		fmt.Fprintf(&record, "%s,sha256=%s,%d\n", p, base64.RawURLEncoding.EncodeToString(sum[:]), len(all[p]))
	}
	record.WriteString(info + "/RECORD,,\n")
	all[info+"/RECORD"] = record.String()
	paths = append(paths, info+"/RECORD")

	out := filepath.Join(dir, dist+"-"+version+"-py3-none-any.whl")
	f, err := os.Create(out)
	if err != nil {
		return "", err
	}
	defer f.Close()
	zw := zip.NewWriter(f)
	for _, p := range paths {
		w, err := zw.Create(p)
		if err != nil {
			return "", err
		}
		if _, err := w.Write([]byte(all[p])); err != nil {
			return "", err
		}
	}
	if err := zw.Close(); err != nil {
		return "", err
	}
	return out, f.Close()
}
