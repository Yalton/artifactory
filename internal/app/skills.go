package app

import (
	"os"
	"path/filepath"

	"repo.billbert.co/artifactory/artifactory/skill"
)

// SkillHarnessDirs are the agent harness folders that receive the skill.
var SkillHarnessDirs = []string{".claude", ".agents", ".opencode"}

// WriteSkills copies SKILL.md into skills/artifactory under each harness
// folder that already exists in dir, and returns the paths it wrote. It never
// creates the harness folder. With missingOnly it leaves an existing copy
// alone, so a re-index keeps a hand-edited skill.
func WriteSkills(dir string, missingOnly bool) ([]string, error) {
	var paths []string
	for _, h := range SkillHarnessDirs {
		if st, err := os.Stat(filepath.Join(dir, h)); err != nil || !st.IsDir() {
			continue
		}
		target := filepath.Join(dir, h, "skills", "artifactory")
		p := filepath.Join(target, "SKILL.md")
		if missingOnly {
			if _, err := os.Stat(p); err == nil {
				continue
			}
		}
		if err := os.MkdirAll(target, 0o755); err != nil {
			return paths, err
		}
		if err := os.WriteFile(p, []byte(skill.Text()), 0o644); err != nil {
			return paths, err
		}
		paths = append(paths, p)
	}
	return paths, nil
}
