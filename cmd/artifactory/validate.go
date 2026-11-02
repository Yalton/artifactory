package main

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
	"repo.billbert.co/artifactory/artifactory/internal/provider"
	"repo.billbert.co/artifactory/artifactory/internal/validate"
)

// moduleReport is one module's entry in the --json output.
type moduleReport struct {
	Dir        string                 `json:"dir"`
	Descriptor *descriptor.Descriptor `json:"descriptor"`
	Problems   []string               `json:"problems"`
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
	var prov provider.Provider
	if spec != "" {
		var err error
		if prov, err = provider.Open(spec); err != nil {
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
		if prov != nil && len(problems) == 0 {
			tags, err := prov.Tags(context.Background(), d.Name)
			if err != nil && !errors.Is(err, provider.ErrNotFound) {
				return out.fail(exitUsage, err.Error())
			}
			for _, t := range tags {
				if t == "v"+d.Version {
					problems = append(problems, "v"+d.Version+" already published")
				}
			}
		}
		r := moduleReport{Dir: dir, Problems: problems}
		if r.Problems == nil {
			r.Problems = []string{}
		}
		if len(problems) == 0 {
			r.Descriptor = &d
			lines = append(lines, dir+": ok")
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
