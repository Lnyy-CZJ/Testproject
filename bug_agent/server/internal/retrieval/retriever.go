package retrieval

import (
	"context"

	"bug-agent/internal/git"
)

// Query defines normalized retrieval input for repository evidence lookup.
type Query struct {
	Repo       *git.Repository
	Text       string
	Keywords   []string
	TopK       int
	RepoName   string
	RepoURL    string
	BranchName string
}

// Evidence represents one retrieval hit.
type Evidence struct {
	FilePath string
	SymbolID string
	Line     int
	Snippet  string
	Score    float64
	Source   string
}

// Retriever is the pluggable retrieval interface.
type Retriever interface {
	Name() string
	Retrieve(ctx context.Context, query Query) ([]Evidence, error)
}
