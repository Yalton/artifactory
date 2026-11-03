// Package arcreg talks to arc, the optional architecture enforcer.
package arcreg

import (
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// RegistryPath is the arc registry, relative to a repository root.
const RegistryPath = ".arch/registry.yaml"

// Warning is returned when a registry exists but arc cannot use it.
const Warning = "arc registry found but arc with module support is not on PATH; module rules not registered"

// Timeout bounds every arc call.
const Timeout = 30 * time.Second

// Detect reports whether arc manages repoRoot: the repository has an arc
// registry and `arc module list --json` exits 0. When the registry exists
// but arc is missing or too old, present is false and warn says so. With no
// registry, present is false and warn is empty.
func Detect(repoRoot string) (present bool, warn string) {
	if _, err := os.Stat(filepath.Join(repoRoot, filepath.FromSlash(RegistryPath))); err != nil {
		return false, ""
	}
	bin, err := exec.LookPath("arc")
	if err != nil {
		return false, Warning
	}
	if out, err := run(repoRoot, bin, "module", "list", "--json"); err != nil {
		return false, Warning + " (`arc module list --json` failed: " + detail(out, err) + ")"
	}
	return true, ""
}
