package main

import (
	"fmt"
	"strings"

	"repo.billbert.co/artifactory/artifactory/internal/descriptor"
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
	for _, a := range args {
		if strings.HasPrefix(a, "-") {
			return out.fail(exitUsage, "validate: unknown flag "+a)
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
