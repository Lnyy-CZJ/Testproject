package service

import (
	"encoding/json"
	"testing"
)

func TestStripMarkdownCodeBlock(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"```json\n{\"title\":\"bug\"}\n```", "{\"title\":\"bug\"}"},
		{"```\n{\"title\":\"bug\"}\n```", "{\"title\":\"bug\"}"},
		{"{\"title\":\"bug\"}", "{\"title\":\"bug\"}"},
		{"```json\n{\"a\":1}\n```\n", "{\"a\":1}"},
	}
	for i, tt := range tests {
		result := stripMarkdownCodeBlock(tt.input)
		if result != tt.expected {
			t.Errorf("case %d: got %q, want %q", i, result, tt.expected)
		}
	}
}

func TestExtractJSONObject(t *testing.T) {
	tests := []struct {
		input       string
		shouldParse bool
	}{
		{`{"title":"bug","severity":"major"}`, true},
		{`Here: {"title":"bug","descriptionMarkdown":"body { color: red; }","severity":"major"} end`, true},
		{"{\"title\":\"bug\",\"descriptionMarkdown\":\"## 现象\\n```css\\n.body { color: red; }\\n```\\n## 预期\"}", true},
		{`no json here`, false},
		{"```json\n{\"title\":\"bug\"}\n```", true},
		{"\xEF\xBB\xBF{\"title\":\"bug\"}", true},
		{`{"a":"b",}`, true},
		{`{"title":"bug","severity":"major","items":["x","y",]}`, true},
	}
	for i, tt := range tests {
		result, err := extractJSONObject(tt.input)
		if tt.shouldParse {
			if err != nil {
				t.Errorf("case %d: unexpected error: %v", i, err)
				continue
			}
			var m map[string]interface{}
			if err := json.Unmarshal([]byte(result), &m); err != nil {
				t.Errorf("case %d: extracted JSON is invalid: %v, got: %s", i, err, result)
			}
		} else {
			if err == nil {
				t.Errorf("case %d: expected error, got nil", i)
			}
		}
	}
}

func TestFixCommonJSONIssues(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{`{"a":"b",}`, `{"a":"b"}`},
		{`{"a":["b","c",]}`, `{"a":["b","c"]}`},
	}
	for i, tt := range tests {
		result := fixCommonJSONIssues(tt.input)
		if result != tt.expected {
			t.Errorf("case %d: got %q, want %q", i, result, tt.expected)
		}
	}
}
