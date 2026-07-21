package yunxiao

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestClient_ListRepositories_RetryOnTransientFailure(t *testing.T) {
	var attempts int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		current := atomic.AddInt32(&attempts, 1)
		if current < 3 {
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(`{"message":"temporary failure"}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`[
			{"id":"1","name":"repo-a","httpUrlToRepo":"https://codeup.aliyun.com/acme/repo-a.git","defaultBranch":"main"}
		]`))
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "token-abc")
	repos, err := client.ListRepositories(context.Background(), "", 1, 20, "")
	if err != nil {
		t.Fatalf("ListRepositories failed after retries: %v", err)
	}
	if len(repos) != 1 {
		t.Fatalf("expected 1 repository, got %d", len(repos))
	}
	if atomic.LoadInt32(&attempts) != 3 {
		t.Fatalf("expected 3 attempts, got %d", attempts)
	}
}

func TestClient_ListRepositories_NoRetryOnBadRequest(t *testing.T) {
	var attempts int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		atomic.AddInt32(&attempts, 1)
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"message":"bad request"}`))
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "token-abc")
	_, err := client.ListRepositories(context.Background(), "", 1, 20, "")
	if err == nil {
		t.Fatalf("expected error on 400 response")
	}
	if atomic.LoadInt32(&attempts) != 1 {
		t.Fatalf("expected 1 attempt for 400 response, got %d", attempts)
	}
}
