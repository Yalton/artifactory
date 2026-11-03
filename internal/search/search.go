// Package search ranks catalog modules against keywords.
package search

import (
	"encoding/json"
	"sort"
	"strings"
	"unicode"

	"repo.billbert.co/artifactory/artifactory/internal/catalog"
)

// Hit is one ranked module.
type Hit struct {
	Module catalog.Module
	Score  float64
}

// Field weights: name and replaces outweigh summary, which outweighs entry.
const (
	wName    = 4.0
	wReplace = 4.0
	wSummary = 2.0
	wEntry   = 1.0
	// threshold is the lowest score reported: one entry-level word match.
	threshold = 1.0
	// minPrefix is the shortest query word that may match by prefix, so
	// "persist" finds "persistent" and "cursor" finds "cursorkit".
	minPrefix = 4
)

var stopwords = map[string]bool{
	"the": true, "a": true, "an": true, "to": true, "of": true, "for": true,
	"and": true, "or": true, "in": true, "on": true, "with": true,
}

// Tokens lowercases s and splits it on non-letters and non-digits.
func Tokens(s string) []string {
	return strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
}

// match reports whether module token t matches query word q: equal, or t
// starts with q when q has at least minPrefix letters. Matching is one-way,
// so "model" never matches "mode".
func match(q, t string) bool {
	return q == t || (len(q) >= minPrefix && strings.HasPrefix(t, q))
}

func fieldHas(tokens []string, q string) bool {
	for _, t := range tokens {
		if match(q, t) {
			return true
		}
	}
	return false
}

// Rank scores mods against the query words. It is case-insensitive, ignores
// stopwords, and keeps a module only when it matches at least half of the
// distinct query words (rounded up) and scores at least the threshold, so a
// single shared word does not hide a gap. It sorts by score
// descending then name, and keeps only ecosystem eco when eco is non-empty.
func Rank(mods []catalog.Module, query []string, eco string) []Hit {
	var qs []string
	distinct := map[string]bool{}
	for _, w := range query {
		for _, t := range Tokens(w) {
			if !stopwords[t] {
				qs = append(qs, t)
				distinct[t] = true
			}
		}
	}
	need := (len(distinct) + 1) / 2
	hits := []Hit{}
	for _, mod := range mods {
		if eco != "" && mod.Ecosystem != eco {
			continue
		}
		name := Tokens(mod.Name)
		summary := Tokens(mod.Summary)
		replaces := Tokens(strings.Join(mod.Replaces, " "))
		entry := Tokens(strings.Join(mod.Entry, " "))
		score := 0.0
		matched := map[string]bool{}
		for _, q := range qs {
			// Each query word counts once, at its best field.
			w := 0.0
			switch {
			case fieldHas(name, q):
				w = wName
			case fieldHas(replaces, q):
				w = wReplace
			case fieldHas(summary, q):
				w = wSummary
			case fieldHas(entry, q):
				w = wEntry
			}
			if w > 0 {
				score += w
				matched[q] = true
			}
		}
		if len(matched) >= need && score >= threshold {
			hits = append(hits, Hit{Module: mod, Score: score})
		}
	}
	sort.SliceStable(hits, func(i, j int) bool {
		if hits[i].Score != hits[j].Score {
			return hits[i].Score > hits[j].Score
		}
		return hits[i].Module.Name < hits[j].Module.Name
	})
	return hits
}

// MarshalJSON renders a hit as name, summary, install and score.
func (h Hit) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Name    string  `json:"name"`
		Summary string  `json:"summary"`
		Install string  `json:"install"`
		Score   float64 `json:"score"`
	}{h.Module.Name, h.Module.Summary, h.Module.Install, h.Score})
}
