package handler

import "testing"

func TestNormalizeRepoURL(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{
			name: "trim slash and git suffix",
			in:   "https://CodeUP.Aliyun.com/acme/repo-a.git/",
			want: "https://codeup.aliyun.com/acme/repo-a",
		},
		{
			name: "drop query and fragment",
			in:   "https://github.com/org/repo.git?ref=main#foo",
			want: "https://github.com/org/repo",
		},
		{
			name: "path-like input",
			in:   "org/repo.git/",
			want: "org/repo",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := normalizeRepoURL(tt.in)
			if got != tt.want {
				t.Fatalf("normalizeRepoURL(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}
