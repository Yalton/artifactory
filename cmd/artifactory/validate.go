package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/project"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
	"repo.billbert.co/artifactory/artifactory/internal/validate"
)

// moduleReport is one module's entry in the --json output.
type moduleReport struct {
	Dir        string                 `json:"dir"`
	Descriptor *descriptor.Descriptor `json:"descriptor"`
	Problems   []string               `json:"problems"`
	// TagCheck is "checked" when a provider was asked whether the version
	// tag is free, "skipped" when no provider was found, and absent when
	// the module had problems before that check.
	TagCheck string `json:"tag_check,omitempty"`
}

// runValidate checks each DIR (default ".") and exits 1 if any has problems.
func runValidate(out *output, args []string) int {
	var spec string
	var dirs []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--provider" || a == "-provider":
			if i+1 >= len(args) {
				return out.fail(exitUsage, "validate: --provider needs a value")
			}
			i++
			spec = args[i]
		case strings.HasPrefix(a, "--provider="):
			spec = strings.TrimPrefix(a, "--provider=")
		case strings.HasPrefix(a, "-"):
			return out.fail(exitUsage, "validate: unknown flag "+a)
		default:
			dirs = append(dirs, a)
		}
	}
	args = dirs
	var flagProv provider.Provider
	if spec != "" {
		var err error
		if flagProv, err = provider.Open(spec); err != nil {
			return out.fail(exitUsage, err.Error())
		}
	}
	if len(args) == 0 {
		args = []string{"."}
	}
	reports := make([]moduleReport, 0, len(args))
	var lines []string
	bad := false
	for _, dir := range args {
		d, problems := validate.Module(dir)
		r := moduleReport{Dir: dir}
		if len(problems) == 0 {
			// The provider is the flag's, else DIR/artifactory.yaml's. It is
			// never cached, so the tag check is never stale.
			prov := flagProv
			if prov == nil {
				var err error
				if prov, err = dirProvider(dir); err != nil {
					return out.fail(exitUsage, err.Error())
				}
			}
			r.TagCheck = "skipped"
			if prov != nil {
				r.TagCheck = "checked"
				published, err := provider.HasTag(context.Background(), prov, d.Name, "v"+d.Version)
				if err != nil {
					return out.fail(exitUsage, err.Error())
				}
				if published {
					problems = append(problems, "v"+d.Version+" already published")
				}
			}
		}
		r.Problems = problems
		if r.Problems == nil {
			r.Problems = []string{}
		}
		if len(problems) == 0 {
			r.Descriptor = &d
			lines = append(lines, dir+": ok")
			if r.TagCheck == "skipped" {
				lines = append(lines, dir+": tag check skipped: no provider")
			}
		} else {
			bad = true
			for _, p := range problems {
				lines = append(lines, fmt.Sprintf("%s: %s", dir, p))
			}
		}
		reports = append(reports, r)
	}
	out.result(strings.Join(lines, "\n"), map[string]any{"modules": reports})
	if bad {
		return exitProblems
	}
	return exitOK
}

// dirProvider opens the provider named in DIR/artifactory.yaml, or returns
// nil when there is no such file. Folders above DIR are not searched.
func dirProvider(dir string) (provider.Provider, error) {
	f, err := project.Load(dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if f.Provider == "" {
		return nil, nil
	}
	return provider.Open(f.ProviderSpec(dir))
}
