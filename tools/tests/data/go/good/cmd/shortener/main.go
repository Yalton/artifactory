package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"

	"repo.billbert.co/artifactory/config"
	"repo.billbert.co/artifactory/httpserver"
	"repo.billbert.co/artifactory/kvstore"
	"repo.billbert.co/artifactory/shortid"
)

type settings struct {
	Addr string `env:"ADDR" default:":8080"`
	Data string `env:"DATA" default:"shortener.json"`
}

func main() {
	var cfg settings
	if err := config.Load("SHORTENER", &cfg, ""); err != nil {
		log.Fatal(err)
	}
	store, err := kvstore.Open(cfg.Data)
	if err != nil {
		log.Fatal(err)
	}
	defer store.Close()

	mux := http.NewServeMux()
	mux.HandleFunc("POST /links", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			URL string `json:"url"`
		}
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.URL == "" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		for {
			code, err := shortid.New(7)
			if err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			added, err := store.PutIfAbsent(code, in.URL)
			if err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			if added {
				w.WriteHeader(http.StatusCreated)
				json.NewEncoder(w).Encode(map[string]string{"code": code})
				return
			}
		}
	})
	mux.HandleFunc("GET /{code}", func(w http.ResponseWriter, r *http.Request) {
		url, ok, err := store.Get(r.PathValue("code"))
		switch {
		case err != nil:
			http.Error(w, err.Error(), http.StatusInternalServerError)
		case !ok:
			http.NotFound(w, r)
		default:
			http.Redirect(w, r, url, http.StatusFound)
		}
	})

	if err := httpserver.Run(context.Background(), cfg.Addr, mux); err != nil {
		log.Fatal(err)
	}
}
