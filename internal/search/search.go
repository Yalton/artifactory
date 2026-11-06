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

// Field weights: a module's name says what it is, its summary what it does,
// and replaces lists the jobs it takes over, which often mention generic
// words ("saving", "loading") in passing. Entry names the API.
const (
	wName    = 4.0
	wSummary = 3.0
	wReplace = 2.0
	wEntry   = 1.0
	// threshold is the lowest score reported: one entry-level word match.
	threshold = 1.0
	// minPrefix is the shortest query stem that may match by prefix, so
	// "persist" finds "persistent" and "cursor" finds "cursorkit".
	minPrefix = 4
	// minStem is the shortest stem a suffix may be cut down to.
	minStem = 3
)

var stopwords = map[string]bool{
	"the": true, "a": true, "an": true, "to": true, "of": true, "for": true,
	"and": true, "or": true, "in": true, "on": true, "with": true,
	"at": true, "by": true, "from": true, "into": true, "via": true,
	"between": true, "during": true, "when": true, "while": true,
	"is": true, "my": true,
}

// Tokens lowercases s and splits it on non-letters and non-digits.
func Tokens(s string) []string {
	return strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
}

// fieldTokens is Tokens plus the parts of each CamelCase word, so
// "RunSaveKit" yields "runsavekit", "run", "save" and "kit".
func fieldTokens(s string) []string {
	var out []string
	for _, w := range strings.FieldsFunc(s, func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}) {
		out = append(out, strings.ToLower(w))
		rs := []rune(w)
		start := 0
		for i := 1; i < len(rs); i++ {
			if unicode.IsUpper(rs[i]) && !unicode.IsUpper(rs[i-1]) {
				out = append(out, strings.ToLower(string(rs[start:i])))
				start = i
			}
		}
		if start > 0 {
			out = append(out, strings.ToLower(string(rs[start:])))
		}
	}
	return out
}

// stem cuts a plural "s", then "ing" or "ed", then a final "e", so "save",
// "saves", "saved" and "saving" all become "sav". A cut that would leave
// fewer than minStem letters is skipped.
func stem(w string) string {
	cut := func(suffix string) {
		if strings.HasSuffix(w, suffix) && len(w)-len(suffix) >= minStem {
			w = strings.TrimSuffix(w, suffix)
		}
	}
	if !strings.HasSuffix(w, "ss") {
		cut("s")
	}
	if strings.HasSuffix(w, "ing") {
		cut("ing")
	} else {
		cut("ed")
	}
	cut("e")
	return w
}

func stems(tokens []string) []string {
	out := make([]string, len(tokens))
	for i, t := range tokens {
		out[i] = stem(t)
	}
	return out
}

// match reports whether module stem t matches query stem q: equal, or t
// starts with q when q has at least minPrefix letters. Matching is one-way,
// so "model" never matches "mode", and "game" (stem "gam") never matches
// "gamepad".
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
// stopwords, and compares stems, so "saving" matches "save". Each distinct
// query word adds the weight of the best field it matches: name, then
// summary, then replaces, then entry.
//
// A module that matches every distinct query word is kept. One that matches
// only some of them is kept when it matches at least a third (rounded up) and
// one of the matches is strong: the word is in its name ("save" for
// RunSaveKit), or it is in its replaces list and no other module searched
// matches it at all ("volume" for SettingsKit). A word several modules share,
// such as "loading", or one a summary uses in passing ("in-game", "toggled"),
// is not enough on its own, so "model loading" reports a gap. Hits scoring under the
// threshold are dropped. Results sort by score descending then name, and keep
// only ecosystem eco when eco is non-empty.
func Rank(mods []catalog.Module, query []string, eco string) []Hit {
	var qs []string
	seen := map[string]bool{}
	for _, w := range query {
		for _, t := range Tokens(w) {
			if stopwords[t] {
				continue
			}
			if s := stem(t); !seen[s] {
				seen[s] = true
				qs = append(qs, s)
			}
		}
	}
	need := (len(qs) + 2) / 3
	type scored struct {
		mod    catalog.Module
		score  float64
		words  []string // matched query words
		strong []string // matched words in the name ("") or replaces
	}
	var cands []scored
	df := map[string]int{} // modules matching each query word
	for _, mod := range mods {
		if eco != "" && mod.Ecosystem != eco {
			continue
		}
		name := stems(fieldTokens(mod.Name))
		summary := stems(fieldTokens(mod.Summary))
		replaces := stems(fieldTokens(strings.Join(mod.Replaces, " ")))
		entry := stems(fieldTokens(strings.Join(mod.Entry, " ")))
		c := scored{mod: mod}
		for _, q := range qs {
			// Each query word counts once, at its best field.
			w := 0.0
			switch {
			case fieldHas(name, q):
				w = wName
				c.strong = append(c.strong, "")
			case fieldHas(summary, q):
				w = wSummary
			case fieldHas(replaces, q):
				w = wReplace
			case fieldHas(entry, q):
				w = wEntry
			}
			if w != wName && fieldHas(replaces, q) {
				c.strong = append(c.strong, q)
			}
			if w > 0 {
				c.score += w
				c.words = append(c.words, q)
				df[q]++
			}
		}
		if len(c.words) > 0 {
			cands = append(cands, c)
		}
	}
	hits := []Hit{}
	for _, c := range cands {
		strong := false
		for _, q := range c.strong {
			strong = strong || q == "" || df[q] == 1
		}
		enough := len(c.words) == len(qs) || (len(c.words) >= need && strong)
		if enough && c.score >= threshold {
			hits = append(hits, Hit{Module: c.mod, Score: c.score})
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
