// Package shortid makes short random identifiers.
package shortid

import (
	"crypto/rand"
	"errors"
)

const alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

// New returns n random base62 characters from crypto/rand.
func New(n int) (string, error) {
	if n <= 0 {
		return "", errors.New("shortid: n must be positive")
	}
	out := make([]byte, 0, n)
	buf := make([]byte, n*2)
	for len(out) < n {
		if _, err := rand.Read(buf); err != nil {
			return "", err
		}
		for _, b := range buf {
			if b < 248 { // 248 = 62*4; reject the rest to avoid modulo bias
				out = append(out, alphabet[b%62])
				if len(out) == n {
					break
				}
			}
		}
	}
	return string(out), nil
}
