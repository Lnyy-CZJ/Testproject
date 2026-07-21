package retrieval

import (
	"context"
	"sort"

	"bug-agent/pkg/logger"
)

const defaultRRFK = 60.0

// Router merges results from multiple retrievers.
type Router struct {
	retrievers []Retriever
	rrfK       float64
}

func NewRouter(retrievers ...Retriever) *Router {
	filtered := make([]Retriever, 0, len(retrievers))
	for _, retriever := range retrievers {
		if retriever != nil {
			filtered = append(filtered, retriever)
		}
	}
	return &Router{retrievers: filtered, rrfK: defaultRRFK}
}

func (r *Router) Retrievers() []Retriever {
	return r.retrievers
}

func (r *Router) Name() string {
	return "router"
}

func (r *Router) Retrieve(ctx context.Context, query Query) ([]Evidence, error) {
	if len(r.retrievers) == 0 {
		return nil, nil
	}
	topK := query.TopK
	if topK <= 0 {
		topK = 10
	}

	type agg struct {
		evidence Evidence
		score    float64
	}
	aggMap := make(map[string]*agg)
	firstSource := make(map[string]string)

	for _, retriever := range r.retrievers {
		evidences, err := retriever.Retrieve(ctx, query)
		if err != nil {
			logger.Errorf("检索失败: %v", err)
			continue
		}
		for idx, ev := range evidences {
			if ev.FilePath == "" {
				continue
			}
			item, ok := aggMap[ev.FilePath]
			if !ok {
				item = &agg{evidence: ev}
				aggMap[ev.FilePath] = item
			}
			item.score += 1.0 / (r.rrfK + float64(idx+1))
			if _, exists := firstSource[ev.FilePath]; !exists {
				firstSource[ev.FilePath] = retriever.Name()
			}
		}
	}

	ranked := make([]*agg, 0, len(aggMap))
	for _, item := range aggMap {
		ranked = append(ranked, item)
	}
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].score == ranked[j].score {
			return ranked[i].evidence.FilePath < ranked[j].evidence.FilePath
		}
		return ranked[i].score > ranked[j].score
	})
	if len(ranked) > topK {
		ranked = ranked[:topK]
	}

	result := make([]Evidence, 0, len(ranked))
	for _, item := range ranked {
		ev := item.evidence
		ev.Score = item.score
		ev.Source = firstSource[ev.FilePath]
		result = append(result, ev)
	}
	return result, nil
}
