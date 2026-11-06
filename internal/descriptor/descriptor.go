// Package descriptor parses and checks a module's module.yaml.
package descriptor

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"gopkg.in/yaml.v3"
)

// GodotCSharp is the godot-csharp ecosystem name.
const GodotCSharp = "godot-csharp"

// Python is the python ecosystem name.
const Python = "python"

// Ecosystems lists the supported module ecosystems.
var Ecosystems = []string{GodotCSharp, "go", Python}

var strFields = []string{"name", "ecosystem", "version", "summary", "install", "liveness", "docs", "example", "test"}
var listFields = []string{"replaces", "setup", "entry"}

var godotLiveness = regexp.MustCompile(`^\[\w+\] live$`)

// pythonLiveness allows hyphens because distribution names have them.
var pythonLiveness = regexp.MustCompile(`^\[[\w-]+\] live$`)

// Descriptor is the parsed content of a module.yaml.
type Descriptor struct {
	Name      string   `yaml:"name" json:"name"`
	Ecosystem string   `yaml:"ecosystem" json:"ecosystem"`
	Version   string   `yaml:"version" json:"version"`
	Summary   string   `yaml:"summary" json:"summary"`
	Replaces  []string `yaml:"replaces" json:"replaces"`
	Install   string   `yaml:"install" json:"install"`
	Setup     []string `yaml:"setup" json:"setup"`
	Entry     []string `yaml:"entry" json:"entry"`
	Liveness  string   `yaml:"liveness" json:"liveness"`
	Docs      string   `yaml:"docs" json:"docs"`
	Example   string   `yaml:"example" json:"example"`
	Test      string   `yaml:"test" json:"test"`
}

// Error is returned by Load when the descriptor has problems.
type Error struct {
	Problems []string
}

func (e *Error) Error() string { return strings.Join(e.Problems, "; ") }

// Load reads and checks dir/module.yaml. The godot-csharp name rule compares
// against the base name of dir.
func Load(dir string) (Descriptor, error) {
	data, err := os.ReadFile(filepath.Join(dir, "module.yaml"))
	if err != nil {
		if os.IsNotExist(err) {
			return Descriptor{}, &Error{[]string{"module.yaml not found"}}
		}
		return Descriptor{}, &Error{[]string{"module.yaml: " + err.Error()}}
	}
	folder := filepath.Base(dir)
	if abs, err := filepath.Abs(dir); err == nil {
		folder = filepath.Base(abs)
	}
	d, problems := Parse(data, folder)
	if len(problems) > 0 {
		return Descriptor{}, &Error{problems}
	}
	return d, nil
}

// Parse checks module.yaml content. folder is the name the godot-csharp name
// rule compares against. The returned problems are empty when valid.
func Parse(data []byte, folder string) (Descriptor, []string) {
	var raw any
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return Descriptor{}, []string{"invalid YAML: " + err.Error()}
	}
	m, ok := raw.(map[string]any)
	if !ok {
		return Descriptor{}, []string{"must be a mapping"}
	}

	// Numbers keep their source text (version: 1.0 stays "1.0", as in Python).
	var nodes map[string]yaml.Node
	_ = yaml.Unmarshal(data, &nodes)

	var problems []string
	strs := map[string]string{}
	lists := map[string][]string{}
	for _, f := range strFields {
		v := m[f]
		s, isScalar := scalarString(v)
		if n, ok := nodes[f]; ok && n.Kind == yaml.ScalarNode && (n.Tag == "!!int" || n.Tag == "!!float") {
			s, isScalar = n.Value, true
		}
		switch {
		case v == nil || (isScalar && strings.TrimSpace(s) == "") && isStr(v):
			problems = append(problems, "missing field: "+f)
		case !isScalar:
			problems = append(problems, f+": must be a string")
		default:
			strs[f] = strings.TrimSpace(s)
		}
	}
	for _, f := range listFields {
		v := m[f]
		if v == nil {
			if f == "setup" {
				lists[f] = []string{}
			} else {
				problems = append(problems, "missing field: "+f)
			}
			continue
		}
		items, ok := v.([]any)
		var out []string
		for _, it := range items {
			s, isS := it.(string)
			if !isS {
				ok = false
				break
			}
			out = append(out, strings.TrimSpace(s))
		}
		if !ok {
			problems = append(problems, f+": must be a list of strings")
			continue
		}
		if out == nil {
			out = []string{}
		}
		lists[f] = out
	}

	eco, hasEco := strs["ecosystem"]
	if hasEco && !slices.Contains(Ecosystems, eco) {
		problems = append(problems, "ecosystem: must be one of "+strings.Join(Ecosystems, ", "))
	}
	if s, ok := strs["summary"]; ok && (strings.Contains(s, "\n") || utf8.RuneCountInString(s) >= 100) {
		problems = append(problems, "summary: must be one line under 100 characters")
	}
	if r, ok := lists["replaces"]; ok {
		if len(r) < 1 || len(r) > 5 {
			problems = append(problems, "replaces: needs 1 to 5 items")
		}
		for _, item := range r {
			if item == "" || utf8.RuneCountInString(item) >= 80 {
				problems = append(problems, "replaces: each item must be non-empty and under 80 characters")
				break
			}
		}
	}
	if eco == GodotCSharp {
		if name, ok := strs["name"]; ok && name != folder {
			problems = append(problems, fmt.Sprintf("name: '%s' must match folder name '%s'", name, folder))
		}
		if l, ok := strs["liveness"]; ok && !godotLiveness.MatchString(l) {
			problems = append(problems, "liveness: godot-csharp value must be the exact marker line, like '[FooKit] live'")
		}
	}
	if eco == Python {
		if l, ok := strs["liveness"]; ok && !pythonLiveness.MatchString(l) {
			problems = append(problems, "liveness: python value must be the exact marker line, like '[foo-bar] live'")
		}
	}
	if len(problems) > 0 {
		return Descriptor{}, problems
	}
	return Descriptor{
		Name: strs["name"], Ecosystem: eco, Version: strs["version"], Summary: strs["summary"],
		Replaces: lists["replaces"], Install: strs["install"], Setup: lists["setup"], Entry: lists["entry"],
		Liveness: strs["liveness"], Docs: strs["docs"], Example: strs["example"], Test: strs["test"],
	}, nil
}

func isStr(v any) bool { _, ok := v.(string); return ok }

// scalarString renders a string, int or float (not bool) the way the Python
// validator's str() did.
func scalarString(v any) (string, bool) {
	switch x := v.(type) {
	case string:
		return x, true
	case int:
		return strconv.Itoa(x), true
	case int64:
		return strconv.FormatInt(x, 10), true
	case uint64:
		return strconv.FormatUint(x, 10), true
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64), true
	}
	return "", false
}
