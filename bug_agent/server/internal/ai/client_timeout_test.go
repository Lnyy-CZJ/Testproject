package ai

import "testing"

func TestNewDashScopeClient_UsesExtendedHTTPTimeout(t *testing.T) {
	client := NewDashScopeClient("key", "", "model")
	if client.httpClient == nil {
		t.Fatal("expected http client")
	}
	if client.httpClient.Timeout != defaultAIHTTPTimeout {
		t.Fatalf("timeout = %v, want %v", client.httpClient.Timeout, defaultAIHTTPTimeout)
	}
}

func TestNewOpenAIClient_UsesExtendedHTTPTimeout(t *testing.T) {
	client := NewOpenAIClient("key", "", "model")
	if client.httpClient == nil {
		t.Fatal("expected http client")
	}
	if client.httpClient.Timeout != defaultAIHTTPTimeout {
		t.Fatalf("timeout = %v, want %v", client.httpClient.Timeout, defaultAIHTTPTimeout)
	}
}
